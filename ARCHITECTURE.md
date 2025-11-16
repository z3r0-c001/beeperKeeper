# Beeper Keeper v2.0 - Architecture Documentation

## Overview
Complete rebuild of camera monitoring system using HLS streaming protocol for maximum compatibility and reliability.

## Camera Specifications

### CSI Camera (OV5647 IR)
- **Native resolution**: 2592x1944 (5MP)
- **Target resolution**: 1920x1080 @ 30fps
- **Encoding**: H.264 hardware via rpicam-vid
- **Bitrate**: 3Mbps
- **Latency**: Low (<500ms)

### USB Camera (Logitech C270)
- **Native resolution**: 1280x720 (MJPEG max)
- **Target resolution**: 1280x720 @ 30fps
- **Input format**: MJPEG
- **Encoding**: H.264 software (libx264)
- **Audio**: Opus 64kbps mono
- **Bitrate**: 2.5Mbps

## Complete System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI 3B+ (10.10.10.28)                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐        ┌─────────────┐        ┌──────────────┐           │
│  │ CSI Camera  │        │ USB Camera  │        │   BME680     │           │
│  │  (OV5647)   │        │   (C270)    │        │   Sensor     │           │
│  │ 1080p@30fps │        │ 720p@30fps  │        │   (I2C)      │           │
│  └──────┬──────┘        └──────┬──────┘        └──────┬───────┘           │
│         │                      │                       │                    │
│         │ rpicam-vid           │ ffmpeg                │                    │
│         │ H.264 HW             │ H.264 SW + Opus       │                    │
│         ▼                      ▼                       │                    │
│  ┌──────────────────────────────────────┐             │                    │
│  │         MediaMTX (RTSP + HLS)        │             │                    │
│  │  Port 8554 (RTSP) | Port 8888 (HLS) │             │                    │
│  └──────────────────┬───────────────────┘             │                    │
│                     │                                  │                    │
│                     │                                  ▼                    │
│  ┌──────────────────▼──────────────────┐    ┌─────────────────┐           │
│  │      Flask Web App (Port 8080)      │◀───│ MQTT Publisher  │           │
│  │  - HLS Video Players (hls.js)       │    │ (Sensor Reader) │           │
│  │  - Sensor Data Display               │    └────────┬────────┘           │
│  │  - System Stats                      │             │                    │
│  │  - Camera Controls                   │             │ MQTT Publish       │
│  └─────────────────────────────────────┘             │                    │
│                                                       │                    │
└───────────────────────────────────────────────────────┼────────────────────┘
                                                        │
                           ┌────────────────────────────┘
                           │ MQTT Topics (tcp://10.10.10.7:1883)
                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                       MONITORING SERVER (10.10.10.7)                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐      ┌──────────────┐      ┌──────────────┐           │
│  │    Mosquitto    │─────▶│   Telegraf   │─────▶│  InfluxDB v2 │           │
│  │  MQTT Broker    │      │ MQTT→InfluxDB│      │   Time-Series│           │
│  │   Port 1883     │      │   Collector  │      │   Database   │           │
│  └─────────────────┘      └──────────────┘      └──────┬───────┘           │
│                                                         │                    │
│                                                         ▼                    │
│                                              ┌──────────────────┐           │
│                                              │     Grafana      │           │
│                                              │   Dashboards     │           │
│                                              │  Visualization   │           │
│                                              └──────────────────┘           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Camera Streams
- CSI/USB → rpicam-vid/ffmpeg → MediaMTX → HLS → Browser

### 2. Sensor Data
- BME680 (I2C) → MQTT Publisher → MQTT Broker (.7) → Telegraf → InfluxDB → Grafana
- System Stats → MQTT Publisher → MQTT Broker (.7) → Telegraf → InfluxDB → Grafana

### 3. Web Application
- Flask serves HTML/JS → Loads HLS streams → Fetches sensor data via MQTT/WebSocket or HTTP API

## Protocol: HLS (HTTP Live Streaming)

### Why HLS?
- ✓ Native browser support (HTML5 `<video>` tag)
- ✓ No complex JavaScript players needed
- ✓ Works through Cloudflare tunnels
- ✓ Already configured in MediaMTX
- ✓ Reliable, widely supported
- ✗ Higher latency (2-6 seconds vs WebRTC's 200-500ms)

### HLS Endpoints
- CSI Camera: `http://10.10.10.28:8888/csi_camera/index.m3u8`
- USB Camera: `http://10.10.10.28:8888/usb_camera/index.m3u8`

## Application Stack

### Backend (Raspberry Pi 10.10.10.28)
- **MediaMTX**: RTSP → HLS transcoding
- **rpicam-vid**: CSI camera capture
- **ffmpeg**: USB camera capture & encoding
- **Flask**: Web server (port 8080)
- **MQTT**: Sensor data from BME680

### Frontend
- **HTML5**: Structure
- **Video.js or hls.js**: HLS player library
- **JavaScript**: Sensor data updates, controls
- **CSS**: Styling (match existing look & feel)

## Sensor Data Integration

### MQTT Topics (Published to 10.10.10.7:1883)

**Environmental (BME680):**
- `beeper/sensors/bme680/temperature` - Temperature (°C)
- `beeper/sensors/bme680/humidity` - Humidity (%)
- `beeper/sensors/bme680/pressure` - Pressure (hPa)
- `beeper/sensors/bme680/gas` - Gas resistance (Ω)
- `beeper/sensors/bme680/iaq` - Indoor Air Quality index (0-500)
- `beeper/sensors/bme680/co2_equivalent` - Estimated CO₂ (ppm)

**System Stats:**
- `beeper/system/cpu_percent` - CPU usage (%)
- `beeper/system/memory_percent` - RAM usage (%)
- `beeper/system/disk_percent` - Disk usage (%)
- `beeper/sensors/cpu/temperature` - CPU temperature (°C)

**Camera Metadata:**
- `beeper/camera/csi/metadata` - CSI camera metadata (exposure, gain, etc.)

### Data Access in Flask App

The Flask app will subscribe to these MQTT topics and provide them to the frontend via:
1. **Server-Sent Events (SSE)** - Real-time sensor updates pushed to browser
2. **REST API endpoints** - Latest sensor values on demand

## File Structure (Minimal & Streamlined)

```
v2_0/
├── app.py                   # Flask app (single file, ~300 lines)
├── templates/
│   └── index.html          # Single page app
├── static/
│   ├── style.css           # Styling (inline in HTML to reduce files)
│   └── hls.min.js          # HLS player library
└── config/
    ├── mediamtx.yml        # MediaMTX config
    ├── start_csi.sh        # CSI camera script
    └── start_usb.sh        # USB camera script
```

**Total files: 7** (Architecture document not deployed to Pi)

## Camera Configuration Files

### MediaMTX (config/mediamtx.yml)
- RTSP server on port 8554
- HLS server on port 8888 with low-latency settings
- Two paths: csi_camera, usb_camera

### CSI Camera Script (config/start_csi_camera.sh)
```bash
rpicam-vid --codec h264 --width 1920 --height 1080 --framerate 30 \
  -b 3000000 --profile main --level 4.2 --inline -n -t 0 -o - | \
  ffmpeg -f h264 -i - -c:v copy -f rtsp rtsp://localhost:8554/csi_camera
```

### USB Camera Script (config/start_usb_camera.sh)
```bash
ffmpeg \
  -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate 30 -i /dev/video0 \
  -f alsa -channels 1 -sample_rate 48000 -i hw:1,0 \
  -c:v libx264 -preset veryfast -tune zerolatency \
  -crf 23 -maxrate 2500k -bufsize 5000k -g 60 \
  -c:a libopus -b:a 64k -application voip \
  -f rtsp rtsp://localhost:8554/usb_camera
```

## Features

### Phase 1 (MVP)
- [x] Dual camera HLS streaming
- [ ] Basic HTML5 video players
- [ ] View mode toggle (Dual/CSI/USB)
- [ ] Sensor data display (BME680)
- [ ] System stats display

### Phase 2 (Enhanced)
- [ ] Camera controls (brightness, contrast via MQTT)
- [ ] Screenshot capture
- [ ] Time-lapse recording
- [ ] Alert status indicators
- [ ] Mobile responsive design

## Performance Targets

- **CPU usage**: < 80% sustained on Pi 3B+
- **Stream latency**: 2-4 seconds (HLS typical)
- **Uptime**: 99.9% (with auto-restart)
- **Network bandwidth**: ~6Mbps combined (3Mbps CSI + 2.5Mbps USB + 0.5Mbps overhead)

## Deployment

The application will be deployed on Raspberry Pi 3B+ at 10.10.10.28 and served via Cloudflare tunnel for external access.
