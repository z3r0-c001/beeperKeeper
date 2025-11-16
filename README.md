# Beeper Keeper v2.0 🐔

**Status:** ✅ Production - Deployed & Operational

Streamlined camera monitoring system with hybrid WebRTC/HLS streaming and sensor integration.

## Features

- **Hybrid Dual Camera Streaming**
  - **Local Network (10.10.10.28:8080):** Ultra-low latency WebRTC (<2s)
  - **Cloudflare Tunnel (YOUR_DOMAIN):** Reliable HLS streaming (5-10s)
  - CSI Camera (OV5647 IR): 800x600 @ 15fps with hardware H.264
  - USB Camera (Logitech C270): 640x480 @ 10fps with audio

- **Real-time Sensor Data**
  - BME680 environmental sensor (temp, humidity, pressure, air quality)
  - System stats (CPU, RAM, disk usage, temperature)
  - Camera metadata (exposure, gain, lux, color temp)

- **User Engagement Features**
  - **Who's Viewing** - Real-time list of active viewers (from Cloudflare JWT)
  - **Simple Chat** - Ephemeral polling-based chat for viewer communication
  - Viewing/Away status tracking via page visibility API

- **Monitoring Integration**
  - MQTT → Telegraf → InfluxDB → Grafana (on 10.10.10.7)
  - Live Grafana dashboard with alerts

- **Performance Optimized**
  - CPU usage: ~70% sustained
  - Temperature: 62-63°C (no throttling)
  - Optimized metadata processing (0.2% CPU)
  - Log rotation prevents file bloat

- **Polished UI Design**
  - Consistent teal borders (#14b8a6) across all cards and video feeds
  - Dark theme with glassmorphism effects
  - Responsive grid layout

## File Structure

```
v2_0/
├── app.py                      # Flask application
├── templates/
│   └── index.html             # Single page app
├── static/
│   └── images/
│       ├── chicken_of_despair.png  # Chicken logo
│       └── tinyWaxer.png           # Additional asset
├── config/
│   ├── mediamtx.yml           # MediaMTX configuration
│   └── start_usb_camera.sh    # USB camera script
├── ARCHITECTURE.md            # Technical documentation
└── README.md                  # This file
```

**Total:** 8 files (~1.6MB with images)

## Deployment

**Status:** ✅ Deployed to production at `/opt/beeperKeeper/` on 10.10.10.28

### Services
```bash
# View running services
sudo systemctl status mediamtx      # Streaming server
sudo systemctl status beeperkeeper  # Flask web app
sudo systemctl status mqtt-publisher # Sensor publisher

# Restart services
sudo systemctl restart mediamtx
sudo systemctl restart beeperkeeper
```

### Access
- **Local Network:** http://10.10.10.28:8080 (WebRTC - ultra-low latency)
- **Remote:** https://YOUR_DOMAIN (HLS via Cloudflare tunnel)

### Update Deployment
```bash
# Update Flask app
scp raspberry_pi/app.py pi_user@10.10.10.28:/opt/beeperKeeper/
sudo systemctl restart beeperkeeper

# Update template
scp raspberry_pi/templates/index.html pi_user@10.10.10.28:/opt/beeperKeeper/templates/
sudo systemctl restart beeperkeeper

# Update MediaMTX config
scp raspberry_pi/config/mediamtx.yml pi_user@10.10.10.28:/etc/mediamtx/mediamtx.yml
sudo systemctl restart mediamtx
```

## Requirements

- Python 3.8+
- Flask
- paho-mqtt
- psutil
- MediaMTX (already installed)
- MQTT broker at 10.10.10.7:1883
- mqtt_publisher.py running (for sensor data)

## Changes from v1

### Streaming
- ✅ **Hybrid WebRTC/HLS** - WebRTC for local (<2s latency), HLS for Cloudflare (5-10s)
- ✅ Automatic protocol detection based on access method
- ✅ Proper track configuration (CSI video-only, USB video+audio)
- ✅ Ultra-low latency optimizations

### Performance
- ✅ CPU usage reduced from 98% to 70% (thermal throttling eliminated)
- ✅ Temperature reduced from 70°C to 62-63°C
- ✅ Metadata updater optimized (30.9% → 0.2% CPU)
- ✅ Log rotation implemented (prevents 40MB+ file bloat)
- ✅ YUYV input format for USB camera (saves 10% CPU vs MJPEG)

### Architecture
- ✅ Streamlined codebase
- ✅ Better organized configuration
- ✅ Same exact look and feel as v1
- ✅ More reliable streaming
- ✅ Production-ready deployment

### Resolution & Quality
- ✅ CSI: 800x600 @ 15fps (hardware H.264, 15% CPU)
- ✅ USB: 640x480 @ 10fps (software H.264 + Opus, 55% CPU)
- ✅ Optimized for Raspberry Pi 3B+ thermal limits

## Documentation

- **[V2_PRODUCTION_NOTES.md](./V2_PRODUCTION_NOTES.md)** - Complete production setup, optimizations, and lessons learned
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - System architecture and design
- **[V2_DEPLOYMENT_GUIDE.md](./V2_DEPLOYMENT_GUIDE.md)** - Deployment procedures
- **[V2_SYNC_STATUS.md](./V2_SYNC_STATUS.md)** - Sync status tracking
