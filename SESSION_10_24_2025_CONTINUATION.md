# beeperKeeper Session - October 24, 2025 (CONTINUATION)

Session continuation focusing on local stream access fixes and camera quality optimization.

---

## 🎯 Work Completed

### 1. Local Stream Access Fix ✅
**Problem**: Camera streams showed 404 errors when accessing from local IP (172.16.0.28:8080)
- URL worked: `beepers.goodsupply.farm` (via Cloudflare)
- URL failed: `http://172.16.0.28:8080` (direct local access)

**Root Cause**:
- iframes used relative URLs `/csi_camera` and `/usb_camera`
- These worked via Cloudflare (reverse proxy to MediaMTX)
- Failed locally because Flask (port 8080) doesn't have those endpoints
- MediaMTX serves those endpoints on port 8889

**Solution Implemented**:
Dynamic iframe URL detection based on access method

**Code Location**: `scripts/camera_monitor.py` lines 514-529

**Implementation**:
```html
<!-- Empty iframe sources, filled by JavaScript -->
<iframe id="csiFrame" src=""></iframe>
<iframe id="usbFrame" src=""></iframe>

<script>
    // Detect if accessed via Cloudflare or local IP
    const isCloudflare = window.location.hostname.includes('goodsupply.farm');
    const baseUrl = isCloudflare ? '' : 'http://172.16.0.28:8889';

    // Set iframe sources dynamically
    document.getElementById('csiFrame').src = baseUrl + '/csi_camera';
    document.getElementById('usbFrame').src = baseUrl + '/usb_camera';
</script>
```

**How It Works**:
- **Cloudflare access**: Uses relative URLs (empty baseUrl) - Cloudflare proxies to MediaMTX
- **Local access**: Uses full MediaMTX URLs on port 8889
- Both methods now work correctly

**Trade-off**:
- Audio auto-unmute only works via Cloudflare (same-origin requirement)
- Local access shows expected cross-origin error (harmless, video still works)

### 2. Camera Quality Optimization ✅
**Goal**: Balance CPU usage with stream quality for better performance

**Original Settings (from previous session)**:
- **IR Camera**: 1280x720 @ 30fps, H.264 hardware
- **USB Camera**: 480x360 @ 10fps, VP8 software (reduced for performance)

**Optimized Settings (current)**:
- **IR Camera**: 800x600 @ 15fps, H.264 hardware
- **USB Camera**: 640x480 @ 15fps, VP8 software

**Changes Made**:

**File 1**: `/home/binhex/mediamtx.yml`
```yaml
# Before:
rpicam-vid --width 1280 --height 720 --framerate 30

# After:
rpicam-vid --width 800 --height 600 --framerate 15
```

**File 2**: `/home/binhex/start_usb_camera.sh`
```bash
# Before:
-video_size 480x360 -framerate 10 -b:v 300k -b:a 24k -g 10

# After:
-video_size 640x480 -framerate 15 -b:v 500k -b:a 32k -g 15
```

**Performance Impact**:
- **IR Camera**: Reduced resolution (33% fewer pixels) and framerate (50% reduction)
  - CPU usage dropped significantly
  - Still looks excellent (user feedback: "looks a million times better")
- **USB Camera**: Increased quality back to original settings
  - Better image quality for close-up monitoring
  - CPU usage increased but acceptable

**CPU Usage Comparison**:

| Component | Before Optimization | After Optimization |
|-----------|-------------------|-------------------|
| Load Average | 6.21 | 3.92 |
| IR Camera (rpicam-vid) | ~41% | ~29% |
| USB Camera (ffmpeg) | ~53% | ~179% |
| MediaMTX | 141% | 50% |

**Why This Works**:
- IR camera is used for wide-area night vision - doesn't need ultra-high resolution
- USB camera is close-up with microphone - benefits from better quality
- H.264 hardware encoding on IR camera is efficient even at reduced settings
- VP8 software encoding on USB camera still acceptable at higher quality

---

## 🔧 Technical Details

### MediaMTX Configuration Architecture

**File**: `/home/binhex/mediamtx.yml`

```yaml
paths:
  # CSI Camera (OV5647 IR) - Hardware H.264 encoding
  csi_camera:
    runOnInit: bash -c 'rpicam-vid --codec h264 --metadata /tmp/camera_metadata.json --metadata-format json --width 800 --height 600 --framerate 15 --inline --timeout 0 -o - | ffmpeg -f h264 -i - -c:v copy -f rtsp rtsp://localhost:8554/csi_camera'
    runOnInitRestart: yes

  # USB Webcam (Logitech) - Software VP8 encoding with audio
  usb_camera:
    runOnInit: /home/binhex/start_usb_camera.sh
    runOnInitRestart: yes
```

**Process Flow**:
1. MediaMTX starts and launches both camera processes
2. IR camera: `rpicam-vid` → `ffmpeg` (H.264 copy) → RTSP stream
3. USB camera: Script detects devices → `ffmpeg` (VP8 encode) → RTSP stream
4. MediaMTX serves WebRTC players at `/csi_camera` and `/usb_camera`
5. Flask app embeds these in iframes with dynamic URL detection

### USB Camera Auto-Detection Script

**File**: `/home/binhex/start_usb_camera.sh`

**Key Features**:
- Auto-detects USB video device (searches `/dev/video*` for Logitech)
- Auto-detects USB audio device (searches `arecord -l` for vendor 0x46d)
- Logs detection results for debugging
- Exits with error if devices not found
- Uses optimized ffmpeg settings for quality/performance balance

**ffmpeg Command**:
```bash
ffmpeg \
    -f v4l2 -input_format mjpeg -video_size 640x480 -framerate 15 -i "$USB_VIDEO_DEV" \
    -f alsa -channels 1 -sample_rate 16000 -i "$USB_AUDIO_DEV" \
    -map 0:v:0 -map 1:a:0 \
    -c:v libvpx -quality realtime -speed 8 -threads 2 -b:v 500k -g 15 \
    -c:a libopus -b:a 32k \
    -f rtsp rtsp://localhost:8554/usb_camera
```

**Encoding Parameters Explained**:
- `-quality realtime -speed 8`: Maximum encoding speed, minimal quality loss
- `-threads 2`: Use 2 CPU cores (out of 4 total on Pi 3B+)
- `-b:v 500k`: 500 kbps video bitrate
- `-g 15`: GOP size (keyframe every 15 frames, every 1 second at 15fps)
- `-b:a 32k`: 32 kbps audio bitrate (Opus codec)

### Cross-Origin Security Considerations

**Expected Behavior**:
- **Cloudflare access**: Same origin (goodsupply.farm), audio auto-unmute works
- **Local access**: Cross-origin (8080 vs 8889), audio auto-unmute blocked

**Browser Console Error (Harmless)**:
```
SecurityError: Failed to read a named property 'document' from 'Window':
Blocked a frame with origin "http://172.16.0.28:8080" from accessing a cross-origin frame.
```

**Why It's Harmless**:
- Error comes from auto-unmute code trying to access MediaMTX iframe
- Browser security correctly blocks cross-origin DOM access
- Video streams work perfectly regardless
- Audio can still be manually unmuted by user clicking iframe

**Why We Can't Fix It**:
- Would require MediaMTX and Flask on same port (complex reverse proxy)
- Or running everything through Cloudflare (which already works)
- Local access is for quick checks, production uses Cloudflare

---

## 📊 Deployment Information

**Production Server**: 172.16.0.28 (binhex@)
**Services Running**:
- MediaMTX: Port 8889 (WebRTC streaming)
- Flask: Port 8080 (Web UI)
- Cloudflare Tunnel: Routes beepers.goodsupply.farm to localhost:8080

**Service Management**:
```bash
# Restart camera processes
ssh binhex@172.16.0.28 "sudo pkill -9 ffmpeg && sudo pkill -9 rpicam-vid && sudo pkill -9 mediamtx"
ssh binhex@172.16.0.28 "cd /home/binhex && nohup mediamtx mediamtx.yml > mediamtx.log 2>&1 &"

# Restart Flask app
ssh binhex@172.16.0.28 "pkill -f camera_monitor.py"
ssh binhex@172.16.0.28 "cd /home/binhex && python3 camera_monitor.py > camera_monitor.log 2>&1 &"

# Check processes
ssh binhex@172.16.0.28 "ps aux | grep -E 'mediamtx|ffmpeg|rpicam|camera_monitor' | grep -v grep"
```

**Current Production State**:
- Both cameras streaming successfully
- Load average: ~3.92 (down from 6.21)
- All features from previous session still working:
  - Scattered chicken background
  - Audio autoplay/unmute (via Cloudflare)
  - JWT user tracking
  - Real-time metrics
  - System monitoring

---

## 🔥 Critical Lessons Learned

### 1. IFRAME URL ROUTING WITH DUAL ACCESS METHODS
**Challenge**: Support both Cloudflare tunnel AND direct local access

**Key Insight**:
- Relative URLs work great for single-domain deployment
- Break completely when accessing via different hostnames/ports
- Dynamic JavaScript URL detection solves both use cases

**Pattern Discovered**:
```javascript
const isCloudflare = window.location.hostname.includes('goodsupply.farm');
const baseUrl = isCloudflare ? '' : 'http://172.16.0.28:8889';
// Apply baseUrl to all iframe sources
```

**Why This Works**:
- Detection is simple and reliable (hostname check)
- No server-side configuration needed
- Works immediately on page load
- Handles future hostname changes easily

### 2. CAMERA QUALITY VS CPU TRADEOFF
**Discovery**: Not all cameras need the same quality settings

**Key Realizations**:
- **IR camera** (wide-area night vision): Resolution matters less, framerate can be lower
- **USB camera** (close-up with audio): Quality matters more for detail
- **Hardware encoding** (H.264): Can handle decent resolution with minimal CPU
- **Software encoding** (VP8): CPU-intensive, quality/performance tradeoff critical

**Optimization Strategy**:
1. Identify camera purpose (wide vs close, monitoring vs recording)
2. Match resolution/framerate to actual use case
3. Leverage hardware acceleration where available
4. Accept higher CPU on cameras that need quality
5. User testing confirms "good enough" is actually good enough

**User Feedback Validation**:
- "looks a million times better with IR" - 800x600@15fps is perfect
- No complaints about USB camera quality at 640x480@15fps
- System performance acceptable with load average ~4

### 3. CROSS-ORIGIN SECURITY IS NOT A BUG
**Important Mindset Shift**: Some "errors" are browser features, not bugs

**What Happened**:
- Browser console showed cross-origin errors
- Immediate reaction: "Something is broken, must fix"
- Reality: Security working as intended, not actually a problem

**The Learning**:
- **Expected errors** are different from **actual failures**
- Video streams work fine despite cross-origin error
- Error is from auto-unmute feature attempting cross-origin DOM access
- This is exactly what browser security should prevent

**Best Practice**:
- Document expected errors in code comments
- Distinguish "feature limitation" from "broken functionality"
- Don't waste time trying to "fix" security features
- Provide alternative access method (Cloudflare) where feature works

### 4. PROCESS MANAGEMENT ON RASPBERRY PI
**Issue**: Multiple camera process restarts can leave zombies

**Solution**: Force kill with `-9` before restart
```bash
sudo pkill -9 ffmpeg
sudo pkill -9 rpicam-vid
sudo pkill -9 mediamtx
```

**Why `-9` Is Necessary**:
- Regular `pkill` sends SIGTERM (processes can ignore)
- Camera processes may be stuck in I/O wait
- `-9` sends SIGKILL (kernel forcibly terminates)
- Clean slate for MediaMTX restart

**When to Use**:
- ✅ Development/testing: Quick restarts needed
- ✅ Configuration changes: Must apply new settings
- ⚠️ Production: Use during low-traffic windows
- ❌ Regular operation: Let systemd manage processes

---

## 📦 Files Modified

### Production Server Files (172.16.0.28)

**File**: `/home/binhex/mediamtx.yml`
- **Change**: Reduced IR camera resolution and framerate
- **Line**: `csi_camera` path runOnInit command
- **Backup**: `mediamtx.yml.backup_20251024_202303`

**File**: `/home/binhex/start_usb_camera.sh`
- **Change**: Increased USB camera resolution and framerate
- **Lines**: ffmpeg video_size, framerate, bitrate parameters
- **Backup**: `start_usb_camera.sh.backup_20251024_202303`

**File**: `/home/binhex/camera_monitor.py`
- **Change**: Dynamic iframe URL detection (from previous session)
- **Lines**: 514-529 (iframe source JavaScript)
- **Current**: Deployed from `scripts/camera_monitor_PRODUCTION_WORKING.py`

### Local Repository Files

**File**: `scripts/camera_monitor.py`
- **Status**: Synced with production (from previous session)
- **Contains**: All features including dynamic iframe URLs

**Documentation Files**:
- `SESSION_10_24_2025_FINAL.md` - Previous session work
- `SESSION_10_24_2025_CONTINUATION.md` - This document

---

## 🧠 Key Technical Patterns

### Pattern 1: Dynamic URL Detection for Multi-Access Environments
```javascript
// Detect access method
const isCloudflare = window.location.hostname.includes('goodsupply.farm');
const baseUrl = isCloudflare ? '' : 'http://172.16.0.28:8889';

// Apply to all resources
document.getElementById('csiFrame').src = baseUrl + '/csi_camera';
document.getElementById('usbFrame').src = baseUrl + '/usb_camera';
```

**Use Cases**:
- Applications with multiple access methods (tunnel vs direct)
- Development vs production environment detection
- Internal vs external user routing
- Port-based service separation

### Pattern 2: Camera Quality Optimization Based on Purpose
```yaml
# Wide-area surveillance (IR camera)
rpicam-vid --width 800 --height 600 --framerate 15
# Purpose: Night vision coverage, motion detection
# Optimization: Lower resolution acceptable, hardware encoding efficient

# Close-up monitoring (USB camera)
ffmpeg -video_size 640x480 -framerate 15 -b:v 500k
# Purpose: Detail capture, audio recording
# Optimization: Higher quality needed, CPU cost acceptable
```

**Decision Matrix**:
| Camera Type | Resolution Priority | Framerate Priority | CPU Budget |
|-------------|-------------------|-------------------|------------|
| Wide-area IR | Low | Medium | Minimal |
| Close-up USB | High | Medium | Moderate |
| Recording | High | High | High |
| Motion detect | Low | Low | Minimal |

### Pattern 3: Safe Production Configuration Changes
```bash
# 1. Backup before changes
cp file.conf file.conf.backup_$(date +%Y%m%d_%H%M%S)

# 2. Make changes with sed (repeatable)
sed -i 's/old_value/new_value/g' file.conf

# 3. Verify changes
grep 'new_value' file.conf

# 4. Force restart services
sudo pkill -9 process_name
nohup command > logfile 2>&1 &

# 5. Verify running
ps aux | grep process_name | grep -v grep
```

**Why This Works**:
- Timestamped backups allow rollback
- `sed` changes are scriptable and repeatable
- Verification catches errors before restart
- Force kill ensures clean process state
- Process check confirms successful restart

---

## 🎯 Current System Status

**Access URLs**:
- **Production**: https://beepers.goodsupply.farm (via Cloudflare)
- **Local**: http://172.16.0.28:8080 (direct access)

**Camera Configuration**:
- **IR Camera**: 800x600 @ 15fps, H.264 hardware, ~29% CPU
- **USB Camera**: 640x480 @ 15fps, VP8 software, ~179% CPU
- **MediaMTX**: ~50% CPU serving WebRTC streams

**System Performance**:
- Load average: 3.92 (4 cores = ~98% utilization)
- Memory: 345 MB used / 906 MB total
- Acceptable for 24/7 operation

**Features Working**:
✅ Dual camera streams (both access methods)
✅ Scattered chicken background
✅ Audio autoplay/unmute (Cloudflare access only)
✅ Real-time metrics
✅ JWT user tracking
✅ System monitoring
✅ Camera metadata display

**Known Limitations**:
- Audio auto-unmute only works via Cloudflare (cross-origin security)
- High CPU usage during active viewing (expected for Pi 3B+)
- USB camera software encoding is CPU-intensive (hardware limitation)

---

## 📋 GitHub Preparation Checklist

**Files to Push**:
- [x] `scripts/camera_monitor.py` - Already synced from previous session
- [x] `SESSION_10_24_2025_FINAL.md` - Previous session documentation
- [x] `SESSION_10_24_2025_CONTINUATION.md` - This session documentation

**Production Files NOT in Repo** (server-specific):
- `/home/binhex/mediamtx.yml` - MediaMTX configuration
- `/home/binhex/start_usb_camera.sh` - USB camera startup script
- Note: These are deployment-specific, not source controlled

**Commit Message**:
```
🔧 Fix local stream access + optimize camera quality

- Add dynamic iframe URL detection for local/Cloudflare access
- Reduce IR camera to 800x600@15fps (better CPU efficiency)
- Increase USB camera to 640x480@15fps (better quality)
- Document cross-origin security considerations
- Update session documentation with optimization details

System load reduced from 6.21 to 3.92 while improving stream quality.
Both local (172.16.0.28:8080) and Cloudflare access now working.
```

---

## 💡 Future Improvements

### Performance Optimization
1. **Hardware upgrade**: Consider Raspberry Pi 4 or 5 for better VP8 performance
2. **Codec change**: Investigate H.264 for USB camera if hardware encoder available
3. **Adaptive bitrate**: Adjust quality based on viewer count/CPU load
4. **Stream caching**: Pre-encode common quality levels for faster serving

### Feature Enhancements
1. **Mobile responsive**: Optimize chicken background for mobile viewports
2. **Bandwidth detection**: Auto-adjust quality based on client connection
3. **Recording**: Add motion-triggered recording to database
4. **Alerts**: Integration with chicken coop monitoring (motion, temperature)

### Reliability Improvements
1. **Systemd services**: Convert manual startup to systemd units
2. **Watchdog**: Auto-restart on crash or freeze
3. **Health checks**: API endpoint for service status monitoring
4. **Graceful degradation**: Continue serving one camera if other fails

---

## 🚨 DO NOT FORGET

1. **Test both access methods** - Cloudflare AND local IP after any iframe changes
2. **Document expected errors** - Cross-origin is feature, not bug
3. **Backup before config changes** - Timestamped backups allow rollback
4. **Verify process state** - Check CPU and running processes after restarts
5. **User feedback matters** - "Looks a million times better" = optimization success
6. **Push to GitHub immediately** - No work is done until it's in version control

---

**Session Status**: ✅ COMPLETE AND DEPLOYED
**Production Status**: ✅ FULLY OPERATIONAL (both access methods)
**Performance Status**: ✅ OPTIMIZED (load average 3.92 vs previous 6.21)
**Documentation Status**: ✅ COMPREHENSIVE WITH LEARNINGS
**GitHub Status**: ⏳ READY TO PUSH

Clean, working, documented, and ready for version control. This is how it's done.
