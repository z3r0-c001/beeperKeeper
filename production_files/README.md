# motionOne Production Camera Server - 24/7 Critical Monitoring

Production-ready camera surveillance system for Raspberry Pi 3B+ with OV5647 IR camera module.

## Hardware

- **Board**: Raspberry Pi 3 Model B Plus Rev 1.3
- **Camera**: OV5647 5MP (Arducam 3.6mm IR 1080P with adjustable focus)
- **IR LEDs**: 2x infrared LEDs (always-on)
- **Connection**: CSI (Camera Serial Interface)
- **Network**: 172.16.0.28 (motionOne)

## Features

### Critical 24/7 Reliability
- ✅ **Aggressive auto-restart** - restarts on ANY failure within 10 seconds
- ✅ **Watchdog protection** - auto-exits if camera hangs for 120+ seconds
- ✅ **Health monitoring** - checks camera status every 30 seconds
- ✅ **Resource limits** - prevents system lockup (85% CPU, 300MB RAM)
- ✅ **Rate limiting** - allows up to 10 restarts per 5 minutes
- ✅ **Process cleanup** - force-kills stuck processes on shutdown
- ✅ **Auto-start on boot** - systemd enabled for automatic startup

### Camera Configuration
- **Resolution**: 1280x720 (720p) optimized for Pi 3B+
- **Frame Rate**: 15 fps
- **JPEG Quality**: 65 (balanced quality/performance)
- **Rotation**: 180° (hflip + vflip)
- **Format**: RGB888 via libcamera ISP pipeline

### Monitoring & APIs
- **Web Interface**: http://172.16.0.28:8080
- **Health Endpoint**: `/health` - Returns JSON status
- **Stats API**: `/api/stats` - Real-time sensor data (lux, exposure, gain, temperature)
- **Video Feed**: `/video_feed` - MJPEG stream

## Installation

### 1. Install Dependencies
```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-flask libcamera-apps
```

### 2. Deploy Files
```bash
# Copy to Pi
scp camera_server.py binhex@172.16.0.28:/home/binhex/
scp start_camera.sh binhex@172.16.0.28:/home/binhex/
scp motion-camera.service binhex@172.16.0.28:/tmp/

# SSH to Pi
ssh binhex@172.16.0.28

# Make executable
chmod +x ~/start_camera.sh

# Create log file
sudo mkdir -p /var/log
sudo touch /var/log/camera_server.log
sudo chown binhex:binhex /var/log/camera_server.log

# Install systemd service
sudo cp /tmp/motion-camera.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable motion-camera.service
sudo systemctl start motion-camera.service
```

### 3. Verify Installation
```bash
# Check service status
sudo systemctl status motion-camera.service

# Check health
curl http://localhost:8080/health

# View logs
sudo journalctl -u motion-camera.service -f
```

## Service Management

```bash
# Start service
sudo systemctl start motion-camera.service

# Stop service
sudo systemctl stop motion-camera.service

# Restart service
sudo systemctl restart motion-camera.service

# Check status
sudo systemctl status motion-camera.service

# View logs (live)
sudo journalctl -u motion-camera.service -f

# View last 100 lines
sudo journalctl -u motion-camera.service -n 100

# Disable auto-start
sudo systemctl disable motion-camera.service

# Enable auto-start
sudo systemctl enable motion-camera.service
```

## Monitoring

### Health Check
```bash
curl http://172.16.0.28:8080/health
```
Returns:
```json
{
  "status": "healthy",
  "frame_age": 0.08,
  "error_count": 0
}
```

### Sensor Stats
```bash
curl http://172.16.0.28:8080/api/stats
```
Returns:
```json
{
  "lux": 148.2,
  "exposure": 33216,
  "gain": 7.8125,
  "temperature": 2430,
  "health": "healthy",
  "timestamp": "2025-10-23T14:38:15.060317"
}
```

## Architecture

### Components

1. **camera_server.py** - Main application
   - Flask web server
   - libcamera/picamera2 integration
   - Health monitoring threads
   - Watchdog timers
   - RESTful APIs

2. **start_camera.sh** - Startup wrapper
   - Signal handling (SIGTERM, SIGINT)
   - Graceful shutdown (10s grace period)
   - Process cleanup
   - Exit code propagation

3. **motion-camera.service** - Systemd service
   - Resource limits (CPU, memory, tasks)
   - Aggressive restart policy (`Restart=always`)
   - Rate limiting (10 restarts per 5 minutes)
   - Auto-start on boot

### Data Flow
```
OV5647 Sensor → CSI Interface → unicam driver → libcamera ISP → 
picamera2 → JPEG encoder → Flask MJPEG stream → Web clients
```

## Configuration

Edit `/home/binhex/camera_server.py` to modify:

```python
@dataclass
class Config:
    CAMERA_RESOLUTION = (1280, 720)  # Resolution
    CAMERA_FPS = 15                   # Frame rate
    JPEG_QUALITY = 65                 # JPEG quality (1-100)
    METADATA_UPDATE_INTERVAL = 0.5    # Seconds
    HEALTH_CHECK_INTERVAL = 30        # Seconds
    MAX_INIT_RETRIES = 5              # Camera init retries
    INIT_RETRY_DELAY = 5              # Seconds between retries
    WATCHDOG_TIMEOUT = 120            # Seconds - auto-exit if stuck
    MAX_FRAME_AGE = 10                # Seconds - report unhealthy
```

## Reliability Testing Results

All critical failure scenarios tested and verified:

| Test | Result | Recovery Time |
|------|--------|---------------|
| Process crash (kill -9) | ✅ PASS | 10 seconds |
| 5x rapid crashes | ✅ PASS | ~10s each |
| 3x service restarts | ✅ PASS | ~10s each |
| Clean shutdown | ✅ PASS | No stuck processes |
| Auto-start on boot | ✅ PASS | Verified enabled |

## Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u motion-camera.service -n 50

# Check camera hardware
ls -l /dev/video0 /dev/media*
v4l2-ctl --list-devices

# Verify permissions
groups binhex  # Should include 'video'
```

### Camera initialization fails
```bash
# Check libcamera
libcamera-hello --list-cameras

# Test camera manually
python3 -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
```

### High CPU usage
```bash
# Check process
ps aux | grep camera_server

# If stuck, restart
sudo systemctl restart motion-camera.service
```

### Logs filling disk
```bash
# Log rotation is configured (10MB × 5 files)
# Manual cleanup if needed:
sudo truncate -s 0 /var/log/camera_server.log
sudo journalctl --vacuum-time=7d
```

## Known Limitations

1. **Flask Development Server** - Uses Flask's built-in server (not production WSGI). Acceptable for this use case, but could be upgraded to gunicorn if needed.

2. **IR LEDs Always On** - Hardware issue with photoresistors. IR illumination is always active, visible as pink/magenta tint in images.

3. **Group Membership Required** - User must be in 'video' group for camera access.

4. **Systemd Watchdog** - Currently not integrated with systemd watchdog (internal watchdog only). Could be enhanced with `systemd-python`.

## Security Notes

- Service runs as user `binhex` (not root)
- Minimal security hardening to allow camera access
- No authentication on web interface - use firewall rules if exposed
- Logs may contain sensitive camera metadata

## Performance

- **CPU Usage**: ~10-15% steady state (Pi 3B+)
- **Memory**: ~100-120 MB
- **Network**: ~1-2 Mbps for MJPEG stream (depends on clients)
- **Startup Time**: ~5-8 seconds from service start to first frame

## License

Production deployment for private surveillance use.

## Support

For issues, check:
- System logs: `sudo journalctl -u motion-camera.service -f`
- Application logs: `/var/log/camera_server.log`
- Health endpoint: http://172.16.0.28:8080/health
