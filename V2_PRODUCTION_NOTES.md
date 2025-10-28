# Beeper Keeper v2.0 - Production Notes & Lessons Learned

## Production Status: ✅ DEPLOYED & OPERATIONAL

**Deployment Date:** October 25, 2025
**Platform:** Raspberry Pi 3B+ @ YOUR_PI_IP
**Access:** Local (WebRTC) + Cloudflare Tunnel (HLS)

---

## 🎯 Final Specifications

### CSI Camera (OV5647 IR Night Vision)
- **Resolution:** 800x600 @ 15fps
- **Encoding:** H.264 **hardware** (rpicam-vid)
- **CPU Usage:** ~15%
- **Tracks:** Video only (H.264)
- **Latency:** <1s (WebRTC) / 5-10s (HLS)
- **Capture:** `rpicam-vid --codec h264 --width 800 --height 600 --framerate 15`

### USB Camera (Logitech C270)
- **Resolution:** 640x480 @ 10fps
- **Input Format:** YUYV422 (not MJPEG - saves CPU)
- **Encoding:** H.264 **software** (libx264)
- **Audio:** Opus 48kbps mono
- **CPU Usage:** ~55%
- **Tracks:** Video (H.264) + Audio (Opus)
- **Latency:** <2s (WebRTC) / 5-10s (HLS)
- **Bitrate:** 800kbps max

### System Performance
- **Total CPU Usage:** ~70% sustained
- **CPU Temperature:** 62-63°C (case open)
- **Throttle Status:** None (below 70°C threshold)
- **CPU Frequency:** 1400MHz (no throttling)
- **Memory:** ~45% utilization

---

## 🏗️ Hybrid Streaming Architecture

### The Problem: Cloudflare Tunnel + WebRTC Incompatibility
**Discovery:** WebRTC uses UDP for peer connections, but Cloudflare tunnels only proxy HTTP/HTTPS traffic. WebRTC cannot traverse Cloudflare tunnels.

### The Solution: Smart Protocol Selection
```javascript
const isCloudflare = window.location.hostname.includes('YOUR_DOMAIN');
const useWebRTC = !isCloudflare && (window.location.hostname === 'YOUR_PI_IP');

if (useWebRTC) {
    // Local network: Ultra-low latency WebRTC (<2s)
    initWebRTC();
} else {
    // Cloudflare tunnel: Reliable HLS streaming (5-10s)
    initHLS();
}
```

### Streaming Protocols by Access Method

| Access Method | Protocol | Latency | Port | Use Case |
|--------------|----------|---------|------|----------|
| **Local Network** (YOUR_PI_IP:8080) | WebRTC (WHEP) | 0.5-2s | 8889 | Real-time monitoring |
| **Cloudflare Tunnel** (YOUR_DOMAIN) | HLS | 5-10s | 8888 | Remote access |

---

## 🔧 Critical Bug Fix: CSI Camera WebRTC Track Mismatch

### The Problem
**Symptom:** CSI camera WebRTC connection established successfully (MediaMTX logs confirmed), but video element not displaying in browser. USB camera worked fine.

**Root Cause:** JavaScript was requesting BOTH video AND audio transceivers for both cameras:
```javascript
pc.addTransceiver('video', { direction: 'recvonly' });
pc.addTransceiver('audio', { direction: 'recvonly' });  // ❌ CSI has no audio!
```

But camera track configurations differ:
- **CSI Camera:** 1 track (H264 video only)
- **USB Camera:** 2 tracks (H264 video + Opus audio)

When the browser requested an audio track that didn't exist, the stream failed to render.

### The Fix
Made audio transceiver conditional based on camera capabilities:

```javascript
async function startWebRTC(videoElementId, whepUrl, hasAudio = true) {
    // ...
    pc.addTransceiver('video', { direction: 'recvonly' });
    if (hasAudio) {  // ✓ Only add audio when camera provides it
        pc.addTransceiver('audio', { direction: 'recvonly' });
    }
    // ...
}

// Usage
await startWebRTC('csiVideo', WEBRTC_BASE + '/csi_camera/whep', false);  // video only
await startWebRTC('usbVideo', WEBRTC_BASE + '/usb_camera/whep', true);   // video + audio
```

**Files Modified:** `/opt/beeperKeeper/templates/index.html`
**Lines:** 404-419 (startWebRTC function), 399-400 (initWebRTC calls)

### Lesson Learned
**Always match WebRTC transceiver requests to actual stream capabilities.** Query the MediaMTX API (`/v3/paths/get/{name}`) to discover track configuration before initializing WebRTC connections.

---

## ⚡ Performance Optimizations

### 1. Metadata Updater CPU Reduction (30.9% → 0.2%)

**Problem:** `metadata_updater.py` was reading entire 40MB file every second.

**Fix:** Read only last 10KB using file seeking:
```python
with open(STREAM_FILE, 'rb') as f:
    f.seek(0, 2)  # Seek to end
    file_size = f.tell()
    read_size = min(10240, file_size)  # Read last 10KB max
    f.seek(max(0, file_size - read_size))
    content = f.read().decode('utf-8', errors='ignore')
```

**Result:** 99.4% CPU reduction (30.9% → 0.2%)

### 2. Camera Metadata Log Rotation

**Problem:** `/tmp/camera_metadata_stream.txt` growing to 40MB+ indefinitely.

**Fix:** Created rotation script at `/opt/beeperKeeper/rotate_camera_logs.sh`:
```bash
# Rotate when exceeds 10MB, keep last 1MB
if [ "$FILE_SIZE" -gt "$MAX_SIZE_BYTES" ]; then
    tail -c 1048576 "$STREAM_FILE" > "${STREAM_FILE}.tmp"
    mv "${STREAM_FILE}.tmp" "$STREAM_FILE"
fi
```

**Crontab:** `*/5 * * * * /opt/beeperKeeper/rotate_camera_logs.sh`

**Result:** File maintained at ~1.5MB

### 3. USB Camera Optimization Progression

| Iteration | Config | CPU | Temp | Notes |
|-----------|--------|-----|------|-------|
| 1 | 15fps MJPEG input | 67.9% | 70°C | Thermal throttling |
| 2 | 10fps MJPEG input | 58.0% | 67°C | Reduced framerate |
| 3 | 10fps YUYV input | 52.4% | 66°C | Bypassed MJPEG decode |
| 4 | 10fps YUYV + ultra low-latency | 54.7% | 62-63°C | Final config |

**Key Insight:** Switching from MJPEG to YUYV422 input format saved ~10% CPU by eliminating the MJPEG decompression step before H.264 encoding.

### 4. Ultra Low-Latency FFmpeg Flags

Added to USB camera script:
```bash
-fflags nobuffer -flags low_delay -strict experimental
-x264opts bframes=0:keyint=20:min-keyint=20:no-scenecut
-bufsize 400k  # Reduced from 1600k
-rtsp_transport tcp
```

**Effect:** Reduced encoding pipeline latency from ~500ms to ~100-200ms. (HLS protocol still adds 5-10s, but WebRTC benefits fully)

---

## 🌡️ Thermal Management

### Initial State
- **Temperature:** 70°C (thermal throttling at 70°C threshold)
- **Throttle Status:** `0x80008` (soft temp limit + historical event)
- **CPU Frequency:** 1200MHz (throttled from 1400MHz)
- **Ambient:** 19.5°C (case open)

### Solutions Applied
1. ✅ Reduced USB camera from 15fps → 10fps (-10% CPU)
2. ✅ Switched USB input from MJPEG → YUYV (-6% CPU)
3. ✅ Opened case (physical cooling)
4. ✅ Optimized metadata_updater (-30% CPU)

### Final State
- **Temperature:** 62-63°C (7-8°C reduction)
- **Throttle Status:** None
- **CPU Frequency:** 1400MHz (full speed)
- **Total CPU:** ~70% (from ~98%)

### Lesson Learned
**Raspberry Pi 3B+ thermal throttling is at 70°C, not under-voltage.**
Initial misdiagnosis: Thought `0x80008` indicated power issue, but Bit 3 = soft temp limit, Bit 19 = historical temp event.
**Hardware encoder vs software encoder:** CSI camera at 15fps uses 15% CPU (HW), USB camera at 10fps uses 55% CPU (SW).

---

## 📡 MediaMTX Configuration

### Ports
- **RTSP:** 8554 (backend camera ingestion)
- **HLS:** 8888 (HTTP Live Streaming)
- **WebRTC:** 8889 (WHEP protocol)
- **API:** 9997 (path/session management)

### Paths
```yaml
paths:
  csi_camera:
    runOnInit: /opt/beeperKeeper/config/start_csi_camera.sh
    runOnInitRestart: yes

  usb_camera:
    runOnInit: /opt/beeperKeeper/config/start_usb_camera.sh
    runOnInitRestart: yes
```

### WebRTC Settings
```yaml
webrtc: yes
webrtcAddress: :8889
webrtcICEServers2: []  # Local network only, no STUN/TURN needed
```

---

## 🐍 Flask Application Architecture

### Proxy Routes for Cloudflare Compatibility
Flask proxies MediaMTX HLS streams to stay within Cloudflare tunnel:

```python
@app.route('/csi_camera/<path:subpath>')
def proxy_csi_camera(subpath):
    url = f'http://localhost:{MEDIAMTX_HLS_PORT}/csi_camera/{subpath}'
    resp = requests.get(url, stream=True, timeout=10)
    return Response(resp.iter_content(chunk_size=8192),
                   content_type=resp.headers.get('Content-Type'),
                   headers={'Access-Control-Allow-Origin': '*'})
```

**Why?** Cloudflare tunnel terminates at Flask (port 8080). Direct access to port 8888 wouldn't work through the tunnel.

### Dynamic URL Generation
```python
def get_base_url():
    host = request.host.lower()
    if 'YOUR_DOMAIN' in host or 'localhost' in host:
        return ''  # Use relative URLs (stay in tunnel)
    else:
        return f'http://{request.host.split(":")[0]}:{MEDIAMTX_HLS_PORT}'
```

---

## 📊 MQTT Topics & Data Flow

### Published Topics (to YOUR_MQTT_BROKER_IP:1883)
```
beeper/sensors/bme680/all          - All BME680 readings (JSON)
beeper/sensors/cpu/temperature     - CPU temp
beeper/system/stats                - CPU%, memory%, disk%
beeper/camera/csi/metadata         - Exposure, gain, lux, color temp
beeper/audio/level                 - Audio level in dB from USB microphone
```

### MQTT → InfluxDB → Grafana Pipeline
1. **mqtt_publisher.py** reads sensors and publishes to MQTT
2. **Telegraf** (on .7) subscribes and writes to InfluxDB
3. **Grafana** queries InfluxDB for dashboards
4. **Flask app** also subscribes for real-time web display

### Audio Monitoring via ALSA dsnoop
**Problem:** USB webcam microphone needed to be shared between ffmpeg streaming and audio level monitoring.

**Solution:** ALSA dsnoop plugin allows multiple programs to capture from the same device simultaneously.

**Configuration** (`~/.asoundrc` on Raspberry Pi):
```
pcm.dsnoop_usb {
    type dsnoop
    ipc_key 5978293
    ipc_perm 0666
    slave {
        pcm "hw:1,0"
        channels 1
        rate 48000
        format S16_LE
    }
}
```

**Files Modified:**
- `~/.asoundrc` - Added dsnoop device
- `/opt/beeperKeeper/config/start_usb_camera.sh` - Changed from `hw:1,0` to `dsnoop_usb`
- `/opt/beeperKeeper/mqtt_publisher.py` - Added `get_audio_level()` function

---

## 🚀 Deployment & Services

### Systemd Services
```bash
# MediaMTX (streaming server)
sudo systemctl status mediamtx

# Flask web app
sudo systemctl status beeperkeeper

# MQTT publisher (sensor reader)
sudo systemctl status mqtt-publisher

# Metadata updater
# Running as background process, monitored by systemd or cron
```

### Installation Locations
```
/opt/beeperKeeper/
├── app.py
├── templates/
│   └── index.html
├── static/
│   └── images/
│       └── chicken_of_despair.png
├── config/
│   ├── mediamtx.yml
│   ├── start_csi_camera.sh
│   └── start_usb_camera.sh
├── metadata_updater.py
├── rotate_camera_logs.sh
└── mqtt_publisher.py
```

### Camera Script Locations
```bash
/opt/beeperKeeper/config/start_csi_camera.sh
/opt/beeperKeeper/config/start_usb_camera.sh
```

### Logs
```bash
# MediaMTX
journalctl -u mediamtx -f

# Flask app
journalctl -u beeperkeeper -f

# Camera metadata
tail -f /tmp/camera_metadata_stream.txt

# Metadata updater
tail -f /tmp/metadata_updater.log
```

---

## 🎓 Key Lessons Learned

### 1. WebRTC Track Configuration Must Match Stream
Always query stream capabilities before setting up WebRTC transceivers. Don't assume all streams have audio.

### 2. YUYV > MJPEG for USB Cameras
If you're going to encode to H.264 anyway, use YUYV input to skip MJPEG decompression. Saves ~10% CPU.

### 3. File I/O Optimization Is Critical
Reading 40MB files every second = 30% CPU. Reading last 10KB = 0.2% CPU. Always use file seeking for log tailing.

### 4. Cloudflare Tunnels Don't Support WebRTC
WebRTC requires UDP. Cloudflare tunnels are HTTP/HTTPS only. Use hybrid approach with HLS fallback.

### 5. Hardware Encoding Is 3-4x More Efficient
- CSI (hardware H.264): 15% CPU @ 15fps
- USB (software H.264): 55% CPU @ 10fps

### 6. Raspberry Pi 3B+ Thermal Management
- Throttles at 70°C (not under-voltage at 0x80008)
- Case open + reduced CPU load = 7-8°C reduction
- Keep total CPU usage under 75% for sustained operation

### 7. HLS Latency Is Protocol-Inherent
No amount of ffmpeg tuning can reduce HLS latency below 5-10 seconds due to segment-based architecture. Use WebRTC for real-time.

### 8. Log Rotation Prevents System Degradation
Unbounded log files will eventually kill performance. Always implement rotation for append-only files.

---

## 👥 User Tracking & Chat Features

### Who's Viewing (Active User Tracking)

**Purpose:** Show real-time list of users watching the stream

**Implementation:**
- JWT token extraction from Cloudflare Access header `Cf-Access-Jwt-Assertion`
- Username = email prefix (part before @)
- Local fallback: `local-{IP}` for non-Cloudflare access
- Ephemeral in-memory storage (resets on Flask restart)

**User States:**
1. **Viewing** - Active tab, heartbeat < 1 minute ago
2. **Away** - Tab hidden/switched, heartbeat < 2 minutes ago
3. **Offline** - No heartbeat for 2+ minutes (auto-removed)

**Technical Details:**
- Heartbeat interval: 30 seconds
- Session timeout: 2 minutes
- Page visibility tracking (viewing vs away)
- Beacon API for instant departure notification

**Files Modified:**
- `app.py:40-43` - User tracking storage
- `app.py:198-271` - JWT extraction and user management functions
- `app.py:328-364` - Heartbeat, user_left, and active_users endpoints
- `index.html:478-550` - Frontend heartbeat and user list display

### Simple Chat System

**Purpose:** Allow viewers to communicate in real-time while watching

**Design Philosophy:**
- **Simple** - HTTP polling, no WebSocket complexity
- **No auth** - Uses existing JWT username
- **No moderation** - Pure, unfiltered communication
- **Ephemeral** - Last 50 messages, clears on restart
- **Low overhead** - 3 second polling interval

**Technical Implementation:**

**Backend:**
```python
# In-memory message storage
chat_messages = []  # Last 50 messages
MAX_CHAT_MESSAGES = 50

# API Endpoints:
# POST /api/chat/send - Send message (500 char limit)
# GET /api/chat/messages - Retrieve messages
```

**Frontend:**
- Poll interval: 3 seconds
- Auto-scroll to latest message
- Enter key to send
- HTML escaping for security
- Timestamp display in local time

**Message Format:**
```json
{
  "username": "example_user",
  "message": "The chickens are looking good!",
  "timestamp": 1761432126.979
}
```

**Files Modified:**
- `app.py:45-48` - Chat storage configuration
- `app.py:371-410` - Chat send/retrieve endpoints
- `index.html:340-348` - Chat UI
- `index.html:552-622` - Chat JavaScript functions

### UI Design - Consistent Borders

**Color:** Teal (#14b8a6)
**Rationale:**
- Pops against dark background (#0f172a)
- Modern, professional appearance
- Good contrast without being harsh
- Complements existing blue accents

**Applied To:**
- All 5 metrics cards (2px solid #14b8a6)
- Both video containers (2px solid #14b8a6)
- Chat box and input fields (1-2px solid #14b8a6)
- Send button background (#14b8a6)

**Files Modified:**
- `index.html:240-247` - Card styling
- `index.html:201-208` - Video container styling
- `index.html:343-346` - Chat component styling

---

## 📈 Grafana Dashboard Optimizations (October 28, 2025)

### Dashboard Enhancements

**Changes Applied:**
1. **Panel 307 - Complete Environmental Data Timeline**
   - Added audio level (decibels) with proper legend label "Decibels (dB)"
   - Added lights on/off status derived from Lux readings (0=off, 1=on)
   - Legend labels cleaned up to show friendly names instead of technical field names

2. **Panel 501 - Lux Light Level Gauge**
   - Updated thresholds to match real-world lux values with appropriate colors:
     - 0-10: Black (complete darkness)
     - 10-50: Deep purple (moonlight)
     - 50-100: Purple (dim interior)
     - 100-300: Orange (typical room)
     - 300-500: Yellow (bright room)
     - 500-1000: Bright yellow (office)
     - 1000-10000: Light yellow (very bright)
     - 10000+: White (direct sunlight)

3. **All Gauge Panels** (8 total)
   - Enabled threshold labels on all gauge panels (201, 202, 203, 204, 205, 206, 501, 502, 503, 504)
   - Improved readability by showing threshold values

4. **Panel 506 - Active Alerts & History**
   - Repositioned below "Key Metrics at a Glance" section
   - Fixed overlap issue that was causing display problems
   - Shifted all panels below it down by 12 units for clean layout

5. **Panel 203 - Air Quality**
   - Already had correct value mappings (0-50=Excellent, 51-100=Good, etc.)
   - Mappings match Flask app IAQ classification logic

**Files Modified:**
- `~/beeperKeeper/grafana/dashboards/beeper_sensors.json` - Dashboard configuration
- `~/beeperKeeper/telegraf/telegraf.conf` - Audio topic configuration

### Key Learnings

#### Lights Status from Lux Data
**Discovery:** Instead of creating a separate MQTT topic for lights on/off, we derived it from existing Lux data from camera metadata.

**Implementation:**
```flux
from(bucket: "sensors")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
  |> filter(fn: (r) => r["topic"] == "beeper/camera/csi/metadata")
  |> filter(fn: (r) => r["_field"] == "Lux")
  |> map(fn: (r) => ({ r with _value: if r._value >= 50.0 then 1.0 else 0.0 }))
  |> map(fn: (r) => ({ r with _field: "Lights (0=Off, 1=On)" }))
```

**Benefit:** Reused existing data stream instead of adding new MQTT topic, reducing complexity.

#### Panel Overlap Issues
**Problem:** Panel 506 was positioned at y=28, overlapping with Panel 307 (y=20-37) and Key Metrics section (y=37+).

**Fix:** Moved Panel 506 to y=44 (after Key Metrics gauges), shifted all subsequent panels down by 12 units.

**Lesson:** Always verify gridPos.y coordinates don't overlap when positioning panels. Use a layout visualization tool or check programmatically.

#### Legend Label Cleanup
**Problem:** Default Grafana legend shows technical field names like `mqtt_consumer level_db {host="beeper_telegraf"...}`

**Solution:** Use Flux `map()` function to rename _field to user-friendly labels:
```flux
|> map(fn: (r) => ({ r with _field: "Decibels (dB)" }))
```

**Result:** Clean, professional legend labels in the UI.

---

## 📝 Next Steps & Future Enhancements

### Immediate (Completed)
- [x] WebRTC implementation
- [x] Hybrid streaming (WebRTC + HLS)
- [x] Performance optimization
- [x] Thermal management
- [x] **JWT user tracking** - Show logged-in users from Cloudflare Access token
- [x] **Simple chat system** - Ephemeral polling-based chat for viewer communication
- [x] **Consistent UI borders** - Teal (#14b8a6) borders across all cards and video feeds

### Future Considerations
- [ ] Add second Pi with USB camera only for distributed monitoring
- [ ] Implement motion detection alerts
- [ ] Time-lapse recording feature
- [ ] PTZ camera support (if upgraded hardware)
- [ ] H.265/HEVC encoding (lower bandwidth, but Pi 3B+ lacks HW support)

---

## 🔗 Related Documentation
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Original system architecture
- [V2_DEPLOYMENT_GUIDE.md](./V2_DEPLOYMENT_GUIDE.md) - Deployment procedures
- [V2_SYNC_STATUS.md](./V2_SYNC_STATUS.md) - Sync status tracking
- [MIGRATION_NOTES.md](./MIGRATION_NOTES.md) - v1 to v2 migration and directory cleanup

---

**Document Version:** 2.1
**Last Updated:** October 28, 2025 @ 11:00 EDT
**Status:** Production Ready ✅

**Latest Features:**
- ✅ User tracking (Who's Viewing)
- ✅ Simple chat system
- ✅ Consistent teal UI borders (#14b8a6)
- ✅ WebRTC/HLS hybrid streaming
- ✅ Optimized performance (70% CPU, 62-63°C)
- ✅ Audio monitoring via ALSA dsnoop
- ✅ Grafana dashboard enhancements (lights tracking, threshold labels, panel repositioning)
