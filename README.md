# beeperKeeper

A dual-camera monitoring system for Raspberry Pi with WebRTC streaming, real-time sensor monitoring, and Grafana visualization.

## Overview

beeperKeeper is a complete surveillance solution designed for Raspberry Pi that provides low-latency video streaming, environmental monitoring, and historical data visualization. Perfect for monitoring chicken coops, server rooms, greenhouses, or any space requiring dual-camera coverage with environmental sensing.

## Features

- **Dual Camera Support**: Simultaneous CSI camera (IR night vision) and USB webcam with audio
- **WebRTC Streaming**: Low-latency video via MediaMTX with hardware H.264 encoding
- **Live Audio**: USB webcam microphone streaming with Opus codec
- **Environmental Sensors**: BME680 support for temperature, humidity, pressure, and air quality
- **System Monitoring**: Real-time CPU temperature, usage, memory, and disk stats
- **Grafana Dashboards**: Historical data visualization with automated alerts
- **Responsive Web Interface**: Modern, mobile-friendly monitoring dashboard
- **Docker Deployment**: One-command setup for complete monitoring stack

## Hardware Requirements

### Minimum
- Raspberry Pi 3 Model B+ (4GB RAM recommended)
- CSI camera module (any compatible Pi camera)
- 32GB microSD card
- 5V 3A power supply

### Recommended
- Raspberry Pi 4 or 5 (better performance)
- OV5647 5MP CSI Camera (IR variant for night vision)
- USB webcam with microphone (e.g., Logitech C270)
- BME680 environmental sensor (optional)
- Ethernet connection (WiFi can be unstable for streaming)

## Quick Start

### 1. System Preparation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y git python3 python3-pip libcamera-apps ffmpeg i2c-tools v4l-utils

# Enable I2C (for BME680 sensor)
sudo raspi-config
# Interface Options → I2C → Enable
# Interface Options → Camera → Enable
```

### 2. Install MediaMTX

```bash
# Download MediaMTX (check for latest version)
wget https://github.com/bluenviron/mediamtx/releases/download/v1.9.3/mediamtx_v1.9.3_linux_arm64v8.tar.gz

# Extract and install
tar -xzf mediamtx_v1.9.3_linux_arm64v8.tar.gz
sudo mv mediamtx /usr/local/bin/
sudo chmod +x /usr/local/bin/mediamtx
rm mediamtx_v1.9.3_linux_arm64v8.tar.gz
```

### 3. Clone Repository

```bash
cd ~
git clone https://github.com/z3r0-c001/beeperKeeper.git
cd beeperKeeper
```

### 4. Install Python Dependencies

```bash
# Core dependencies
pip3 install flask psutil

# Environmental sensor (if using BME680)
pip3 install adafruit-circuitpython-bme680

# MQTT for Grafana integration
pip3 install paho-mqtt
```

### 5. Configure System

```bash
# Copy configuration template
cp config.example.py config.py

# Edit with your settings
nano config.py
```

**Key configuration items:**
- `RASPBERRY_PI_IP`: Your Pi's IP address (e.g., `192.168.1.100`)
- `BME680_ENABLED`: `True` if using sensor, `False` otherwise
- `MQTT_BROKER`: `localhost` if running Grafana stack on same Pi

### 6. Deploy Files

```bash
# Copy application files to home directory
cp scripts/camera_monitor.py ~/
cp scripts/mediamtx.yml ~/
cp scripts/mqtt_publisher.py ~/
cp config.py ~/
```

### 7. Start Services

**Terminal 1 - MediaMTX:**
```bash
cd ~
/usr/local/bin/mediamtx mediamtx.yml
```

**Terminal 2 - Web Interface:**
```bash
cd ~
python3 camera_monitor.py
```

**Access the interface:**
Open browser to `http://YOUR_PI_IP:8080`

## Grafana Monitoring Stack (Optional)

For historical data visualization and automated alerts:

### 1. Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install docker-compose -y

# Logout and login for group changes
exit
```

### 2. Configure Docker Stack

```bash
cd ~/beeperKeeper

# Copy docker-compose template
cp docker-compose.example.yml docker-compose.yml

# Edit passwords (IMPORTANT!)
nano docker-compose.yml
```

**Change these passwords:**
- `DOCKER_INFLUXDB_INIT_PASSWORD`
- `DOCKER_INFLUXDB_INIT_ADMIN_TOKEN`
- `GF_SECURITY_ADMIN_PASSWORD`

### 3. Start Grafana Stack

```bash
docker-compose up -d

# Check status
docker-compose ps
```

### 4. Start MQTT Publisher

```bash
cd ~
python3 mqtt_publisher.py &
```

### 5. Access Grafana

Open browser to `http://YOUR_PI_IP:3000`

**Default credentials** (change these!):
- Username: `admin`
- Password: See your `docker-compose.yml`

## Configuration Reference

### config.py Options

```python
# Network Configuration
RASPBERRY_PI_IP = "192.168.1.100"  # Your Pi's IP address
WEBRTC_PORT = 8889                  # MediaMTX WebRTC port
WEB_UI_PORT = 8080                  # Flask web interface port

# Camera Configuration
CSI_CAMERA_STREAM = f"http://{RASPBERRY_PI_IP}:{WEBRTC_PORT}/csi_camera"
USB_CAMERA_STREAM = f"http://{RASPBERRY_PI_IP}:{WEBRTC_PORT}/usb_camera"

# Sensor Configuration
BME680_ENABLED = True               # Enable BME680 sensor
BME680_I2C_ADDRESS = 0x76           # I2C address (0x76 or 0x77)

# System Monitoring
UPDATE_INTERVAL_SECONDS = 2         # Sensor data update frequency

# MQTT Configuration
MQTT_BROKER = "localhost"           # MQTT broker address
MQTT_PORT = 1883                    # MQTT broker port
PUBLISH_INTERVAL_SECONDS = 10       # MQTT publish frequency
```

### MediaMTX Configuration

The `mediamtx.yml` file controls camera streams:

- **CSI Camera**: 1280x720 @ 30fps, H.264 hardware encoding
- **USB Camera**: 640x480 @ 15fps, VP8 video + Opus audio
- **Audio**: Mono microphone @ 16kHz, 32kbps Opus encoding

Edit device paths if your cameras are on different `/dev/video*` devices.

## Camera Setup

### CSI Camera

```bash
# Test CSI camera
rpicam-vid --codec h264 --width 1280 --height 720 --framerate 30 -t 10000 -o test.h264

# List camera devices
libcamera-hello --list-cameras
```

### USB Webcam

```bash
# List video devices
v4l2-ctl --list-devices

# List audio devices
arecord -l

# Test webcam
ffmpeg -f v4l2 -input_format mjpeg -video_size 640x480 -i /dev/video1 -t 10 test.mp4
```

## Troubleshooting

### Camera Issues

**CSI camera not detected:**
```bash
vcgencmd get_camera
libcamera-hello --list-cameras
```

**USB camera not working:**
```bash
lsusb
v4l2-ctl --device=/dev/video1 --list-formats-ext
```

### Streaming Issues

**WebRTC streams not loading:**
- Verify MediaMTX is running: `ps aux | grep mediamtx`
- Check network: `ping YOUR_PI_IP`
- Ensure ports 8080 and 8889 are accessible
- Review MediaMTX terminal output for errors

**High CPU usage:**
- Reduce USB camera framerate in `mediamtx.yml`
- Lower USB camera resolution
- Disable BME680 sensor if not needed

### Sensor Issues

**BME680 not detected:**
```bash
# Check I2C enabled
sudo raspi-config

# Scan I2C bus
sudo i2cdetect -y 1
```

Verify wiring: SDA→GPIO2, SCL→GPIO3, VCC→3.3V, GND→GND

### Grafana Issues

**No data in dashboards:**
```bash
# Check MQTT messages
mosquitto_sub -h localhost -t 'beeper/#' -v

# Check Docker containers
docker-compose logs telegraf
docker-compose logs influxdb
```

## Performance

### Raspberry Pi 3B+ Typical Usage
- CSI Camera H.264: ~5-10% CPU (GPU accelerated)
- USB Camera VP8: ~50-90% CPU (software encoding)
- Total System Load: 180-240% CPU (across 4 cores)
- Memory Usage: ~300-400 MB
- Network: ~2-4 Mbps per stream

### Optimization Tips
- Use Ethernet instead of WiFi
- Reduce USB camera resolution/framerate
- Disable sensors if not needed
- Consider Pi 4 or 5 for better performance

## Auto-Start on Boot

Create systemd services for automatic startup:

```bash
# MediaMTX service
sudo nano /etc/systemd/system/mediamtx.service
```

```ini
[Unit]
Description=MediaMTX Camera Streaming
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/local/bin/mediamtx /home/pi/mediamtx.yml
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Enable services
sudo systemctl daemon-reload
sudo systemctl enable mediamtx.service
sudo systemctl start mediamtx.service
```

Repeat for `camera-monitor.service` and `mqtt-publisher.service`.

## Security Recommendations

1. **Change default passwords** in `docker-compose.yml`
2. **Enable MQTT authentication** for production use
3. **Use firewall** to restrict access to monitoring ports
4. **Keep system updated**: `sudo apt update && sudo apt upgrade`
5. **Use strong passwords** for Grafana and InfluxDB

## Architecture

```
┌─────────────────┐         ┌──────────────┐
│  CSI Camera     │────────>│ rpicam-vid   │
│  (IR Module)    │         │ (H.264 HW)   │
└─────────────────┘         └──────┬───────┘
                                   │
┌─────────────────┐         ┌──────┴───────┐         ┌──────────────┐
│  USB Webcam     │────────>│  MediaMTX    │────────>│   WebRTC     │
│  (with mic)     │         │  (Streaming) │         │  (Port 8889) │
└─────────────────┘         └──────────────┘         └──────────────┘
                                                             │
┌─────────────────┐                                          │
│  BME680 Sensor  │                                          │
│  (I2C)          │                                          │
└────────┬────────┘                                          │
         │                                                   │
         │          ┌──────────────────┐                     │
         └─────────>│  camera_monitor  │<────────────────────┘
                    │  (Flask Web UI)  │
                    │  (Port 8080)     │
                    └──────────────────┘
                             │
                             ↓
                    ┌──────────────────┐
                    │  MQTT Publisher  │
                    └────────┬─────────┘
                             │
                    ┌────────┴─────────┐
                    │   Docker Stack   │
                    │  Mosquitto       │
                    │  ↓               │
                    │  Telegraf        │
                    │  ↓               │
                    │  InfluxDB        │
                    │  ↓               │
                    │  Grafana         │
                    └──────────────────┘
```

## Known Issues

1. **IR LED Control**: IR LEDs may stay always-on (hardware-dependent)
2. **WiFi Stability**: Ethernet strongly recommended for 24/7 streaming
3. **USB Camera CPU**: VP8 software encoding is CPU-intensive on Pi 3B+

## License

This work is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License.

Copyright © 2025 CodeOne Contributors. All rights reserved.

See [LICENSE](LICENSE) file for complete terms.

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Test on actual Raspberry Pi hardware
4. Submit a pull request

## Support

For issues or questions:
- GitHub Issues: https://github.com/z3r0-c001/beeperKeeper/issues
- Ensure you've followed all setup steps
- Check logs for error messages
- Review troubleshooting section

## Acknowledgments

- [MediaMTX](https://github.com/bluenviron/mediamtx) - WebRTC/RTSP streaming server
- [libcamera](https://libcamera.org/) - Raspberry Pi camera stack
- [Adafruit](https://www.adafruit.com/) - CircuitPython BME680 library
- [Grafana](https://grafana.com/) - Data visualization platform

---

**Made for monitoring what matters**
