# beeperKeeper Installation Guide

Complete step-by-step installation guide for deploying beeperKeeper on Raspberry Pi.

## ⚠️ CRITICAL: Placeholder Values Must Be Changed

**This repository contains placeholder values that WILL NOT WORK without customization.**

Before starting installation, understand that you'll need to replace these placeholders:

### Required Customization Summary:

| File | Placeholder | What You Need |
|------|-------------|---------------|
| `config.py` | `RASPBERRY_PI_IP = "192.168.1.100"` | Your Pi's actual IP address |
| `docker-compose.yml` | `CHANGE_ME_influxdb_password` | Strong InfluxDB password |
| `docker-compose.yml` | `CHANGE_ME_influxdb_admin_token_min_32_chars` | Secure token (32+ characters) |
| `docker-compose.yml` | `CHANGE_ME_grafana_password` | Grafana admin password |
| `docker/telegraf/telegraf.conf` | Token placeholder | MUST match InfluxDB token above |
| `docker/grafana/provisioning/alerting/contactpoints.yaml` | `your-email@example.com` | Your actual email for alerts |

**These changes are covered in detail in each installation step below.**

---

## Table of Contents

1. [Hardware Setup](#hardware-setup)
2. [Operating System Installation](#operating-system-installation)
3. [System Configuration](#system-configuration)
4. [Software Installation](#software-installation)
5. [Application Setup](#application-setup)
6. [Grafana Stack Deployment](#grafana-stack-deployment)
7. [Auto-Start Configuration](#auto-start-configuration)
8. [Verification & Testing](#verification--testing)

---

## Hardware Setup

### Required Components

- **Raspberry Pi** (3B+ minimum, 4/5 recommended)
- **CSI Camera Module** (any Pi-compatible camera)
- **USB Webcam with microphone** (e.g., Logitech C270)
- **microSD Card** (32GB minimum, Class 10)
- **Power Supply** (5V 3A minimum)
- **Network Connection** (Ethernet strongly recommended)

### Optional Components

- **BME680 Sensor** - Environmental monitoring (I2C)
- **Heatsink/Fan** - For prolonged high-CPU operations
- **Case** - Protection and cable management

### Hardware Assembly

1. **Install heatsinks** on CPU and RAM chips
2. **Connect CSI camera**:
   - Open CSI port latch
   - Insert ribbon cable (contacts facing away from Ethernet port)
   - Close latch firmly
3. **Connect USB webcam** to any USB port
4. **Connect BME680** (if using):
   - VCC → 3.3V (Pin 1)
   - GND → Ground (Pin 6)
   - SDA → GPIO2 (Pin 3)
   - SCL → GPIO3 (Pin 5)
5. **Insert microSD card**
6. **Connect Ethernet cable**
7. **Connect power** (last step)

---

## Operating System Installation

### Download Raspberry Pi OS

1. Download **Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. Select **Raspberry Pi OS (64-bit)** - Desktop or Lite
3. Write to microSD card

### Configure OS Settings (Pre-Boot)

In Raspberry Pi Imager, click gear icon (⚙️) to configure:

- **Hostname**: `beeperkeeper` (or your preference)
- **Enable SSH**: ✅ Use password authentication
- **Set username/password**: Create secure credentials
- **Configure WiFi**: (if not using Ethernet)
- **Locale Settings**: Set timezone and keyboard layout

### First Boot

1. Insert microSD into Pi and power on
2. Wait ~2 minutes for first boot
3. Find Pi's IP address:
   ```bash
   # From your computer
   ping beeperkeeper.local

   # Or check router's DHCP leases
   ```
4. SSH into Pi:
   ```bash
   ssh pi@beeperkeeper.local
   # or
   ssh pi@192.168.1.XXX
   ```

---

## System Configuration

### Update System

```bash
sudo apt update && sudo apt upgrade -y
```

### Enable Required Interfaces

```bash
sudo raspi-config
```

Navigate to:
1. **Interface Options** → **I2C** → Enable (for BME680)
2. **Interface Options** → **Camera** → Enable
3. **Performance Options** → **GPU Memory** → Set to 256MB
4. **Finish** and reboot:
   ```bash
   sudo reboot
   ```

### Verify Camera Detection

After reboot:

```bash
# CSI camera
vcgencmd get_camera
# Should show: supported=1 detected=1

# List libcamera devices
libcamera-hello --list-cameras

# USB webcam
lsusb | grep -i camera
v4l2-ctl --list-devices
```

### Configure Static IP (Optional but Recommended)

Edit dhcpcd configuration:
```bash
sudo nano /etc/dhcpcd.conf
```

Add at end:
```conf
interface eth0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1 8.8.8.8
```

Reboot to apply:
```bash
sudo reboot
```

---

## Software Installation

### Install System Dependencies

```bash
sudo apt install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    libcamera-apps \
    ffmpeg \
    i2c-tools \
    v4l-utils \
    mosquitto-clients
```

### Install MediaMTX

```bash
# Download latest release (check GitHub for current version)
cd ~
wget https://github.com/bluenviron/mediamtx/releases/download/v1.9.3/mediamtx_v1.9.3_linux_arm64v8.tar.gz

# Extract
tar -xzf mediamtx_v1.9.3_linux_arm64v8.tar.gz

# Install to system
sudo mv mediamtx /usr/local/bin/
sudo chmod +x /usr/local/bin/mediamtx

# Cleanup
rm mediamtx_v1.9.3_linux_arm64v8.tar.gz

# Verify installation
/usr/local/bin/mediamtx --version
```

### Install Python Dependencies

```bash
# Core dependencies
pip3 install flask psutil

# Environmental sensor (BME680)
pip3 install adafruit-circuitpython-bme680

# MQTT for Grafana
pip3 install paho-mqtt
```

### Install Docker & Docker Compose (for Grafana Stack)

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Add user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install docker-compose -y

# Logout and login for group changes
exit
```

(SSH back in after logout)

---

## Application Setup

### Clone Repository

```bash
cd ~
git clone https://github.com/z3r0-c001/beeperKeeper.git
cd beeperKeeper
```

### Configure Application

```bash
# Copy configuration template
cp config.example.py config.py

# Edit configuration
nano config.py
```

**Required changes:**
```python
RASPBERRY_PI_IP = "192.168.1.100"  # Change to your Pi's IP
BME680_ENABLED = True               # False if not using sensor
MQTT_BROKER = "localhost"           # Keep as localhost for Grafana
```

### Deploy Application Files

```bash
# Copy scripts to home directory
cp scripts/camera_monitor.py ~/
cp scripts/mediamtx.yml ~/
cp scripts/mqtt_publisher.py ~/
cp config.py ~/
```

### Test Camera Streams

**Test CSI Camera:**
```bash
rpicam-vid --codec h264 --width 1280 --height 720 --framerate 30 -t 10000 -o test.h264
```

**Test USB Webcam:**
```bash
ffmpeg -f v4l2 -input_format mjpeg -video_size 640x480 -i /dev/video1 -t 5 test.mp4
```

**Test Audio:**
```bash
arecord -l  # List audio devices
arecord -D hw:2,0 -d 5 -f S16_LE -r 16000 -c 1 test.wav
```

### Start Services

**Terminal 1 - MediaMTX:**
```bash
cd ~
/usr/local/bin/mediamtx mediamtx.yml
```

**Terminal 2 - Camera Monitor:**
```bash
cd ~
python3 camera_monitor.py
```

**Access Web Interface:**
Open browser to `http://YOUR_PI_IP:8080`

You should see both camera streams and system stats.

---

## Grafana Stack Deployment

### Configure Docker Stack

```bash
cd ~/beeperKeeper

# Copy docker-compose template
cp docker-compose.example.yml docker-compose.yml

# Edit passwords (REQUIRED!)
nano docker-compose.yml
```

**Change these passwords:**
- Line 29: `DOCKER_INFLUXDB_INIT_PASSWORD=CHANGE_ME_influxdb_password`
- Line 32: `DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=CHANGE_ME_influxdb_admin_token_min_32_chars`
- Line 64: `GF_SECURITY_ADMIN_PASSWORD=CHANGE_ME_grafana_password`

**Update token in Telegraf config:**
```bash
nano docker/telegraf/telegraf.conf
```
Find `token = "CHANGE_ME_influxdb_admin_token_min_32_chars"` and update with same token from docker-compose.yml.

### Start Grafana Stack

```bash
cd ~/beeperKeeper
docker-compose up -d

# Check status
docker-compose ps
# All services should show "Up"

# Check logs
docker-compose logs -f
# Ctrl+C to exit logs
```

### Start MQTT Publisher

**Terminal 3 - MQTT Publisher:**
```bash
cd ~
python3 mqtt_publisher.py
```

### Access Grafana

Open browser to `http://YOUR_PI_IP:3000`

**Login:**
- Username: `admin`
- Password: (what you set in docker-compose.yml)

**Verify Data Flow:**
```bash
# Subscribe to MQTT messages
mosquitto_sub -h localhost -t 'beeper/#' -v

# Should see sensor data every 10 seconds
```

---

## Auto-Start Configuration

Create systemd services for automatic startup on boot.

### MediaMTX Service

```bash
sudo nano /etc/systemd/system/mediamtx.service
```

```ini
[Unit]
Description=MediaMTX Camera Streaming Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/local/bin/mediamtx /home/pi/mediamtx.yml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Camera Monitor Service

```bash
sudo nano /etc/systemd/system/camera-monitor.service
```

```ini
[Unit]
Description=beeperKeeper Camera Monitor Web UI
After=network.target mediamtx.service
Requires=mediamtx.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/bin/python3 /home/pi/camera_monitor.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### MQTT Publisher Service

```bash
sudo nano /etc/systemd/system/mqtt-publisher.service
```

```ini
[Unit]
Description=beeperKeeper MQTT Publisher
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi
ExecStart=/usr/bin/python3 /home/pi/mqtt_publisher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and Start Services

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services (start on boot)
sudo systemctl enable mediamtx.service
sudo systemctl enable camera-monitor.service
sudo systemctl enable mqtt-publisher.service

# Start services now
sudo systemctl start mediamtx.service
sudo systemctl start camera-monitor.service
sudo systemctl start mqtt-publisher.service

# Check status
sudo systemctl status mediamtx.service
sudo systemctl status camera-monitor.service
sudo systemctl status mqtt-publisher.service
```

### Docker Auto-Start

Docker containers already configured with `restart: unless-stopped` in docker-compose.yml, so they'll auto-start on boot.

---

## Verification & Testing

### Check All Services

```bash
# Systemd services
sudo systemctl status mediamtx.service
sudo systemctl status camera-monitor.service
sudo systemctl status mqtt-publisher.service

# Docker containers
cd ~/beeperKeeper
docker-compose ps

# Process list
ps aux | grep -E 'mediamtx|camera_monitor|mqtt_publisher'
```

### Test Web Interface

1. Open `http://YOUR_PI_IP:8080`
2. Verify both camera streams load
3. Check system stats display
4. Check sensor data (if using BME680)

### Test Grafana

1. Open `http://YOUR_PI_IP:3000`
2. Login with your credentials
3. Navigate to Dashboards
4. Open "Beeper Keeper - Sensor Monitoring"
5. Verify data is displaying

### Performance Check

```bash
# CPU temperature
vcgencmd measure_temp

# System resources
htop

# Disk space
df -h

# Network usage
vnstat -l
```

### Reboot Test

```bash
sudo reboot
```

Wait 2 minutes, then verify:
- Web interface accessible
- Grafana accessible
- All services running

---

## Troubleshooting

### Cameras Not Streaming

```bash
# Check MediaMTX logs
sudo journalctl -u mediamtx.service -f

# Check camera devices
ls -la /dev/video*
vcgencmd get_camera
```

### No Sensor Data in Grafana

```bash
# Check MQTT messages
mosquitto_sub -h localhost -t 'beeper/#' -v

# Check Telegraf logs
docker-compose logs telegraf

# Check InfluxDB
docker exec -it beeper_influxdb influx query 'from(bucket:"sensors") |> range(start: -1h) |> limit(n:10)'
```

### High CPU Usage

- Reduce USB camera resolution in `~/mediamtx.yml`
- Lower USB camera framerate
- Disable BME680 if not needed

### Services Won't Start

```bash
# Check service logs
sudo journalctl -u mediamtx.service -n 50
sudo journalctl -u camera-monitor.service -n 50

# Check permissions
ls -la /home/pi/mediamtx.yml
ls -la /home/pi/camera_monitor.py

# Check ports
sudo netstat -tlnp | grep -E '8080|8889|3000|1883'
```

---

## Next Steps

- Configure email alerts in Grafana
- Set up port forwarding for remote access
- Configure SSL/TLS certificates
- Set up automated backups
- Customize Grafana dashboards

---

**Installation complete! Your beeperKeeper system is now operational.**

For support, see [README.md](README.md) troubleshooting section or open a GitHub issue.
