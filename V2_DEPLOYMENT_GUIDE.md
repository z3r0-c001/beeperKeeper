# Beeper Keeper v2.0 - Deployment Guide

## Overview

This directory contains the complete Beeper Keeper v2.0 configuration - a synchronized copy of all deployed files from production servers. This is **separate** from v1 (`/home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/`) and should NOT commingle with v1 files.

## Directory Structure

```
v2_0/
├── docker-compose.yml          # Main stack orchestration (deployed on .7)
├── .env.example               # Environment variables template
├── ARCHITECTURE.md            # System architecture documentation
├── README.md                  # Project overview
│
├── docker/                    # Docker service configurations
│   ├── grafana/
│   │   ├── dashboards/
│   │   │   └── beeper_sensors.json    # Main dashboard (Version 75+)
│   │   ├── provisioning/
│   │   │   ├── alerting/              # Alert rules, contact points, policies
│   │   │   ├── dashboards/            # Dashboard provisioning config
│   │   │   └── datasources/           # InfluxDB connection config
│   │   ├── grafana.ini                # Grafana configuration
│   │   ├── public/
│   │   │   └── custom.css             # Custom Grafana styling
│   │   └── templates/                 # Email alert templates
│   ├── mosquitto/
│   │   ├── config/
│   │   │   └── mosquitto.conf         # MQTT broker configuration
│   │   ├── data/                      # MQTT persistence (runtime)
│   │   └── log/                       # MQTT logs (runtime)
│   └── telegraf/
│       └── telegraf.conf              # MQTT → InfluxDB data pipeline
│
├── images/                    # Shared image assets
│   ├── chicken_of_despair.png
│   ├── chicken_of_despair_email.png
│   ├── good_supply_logo.png
│   └── good_supply_logo_email.png
│
├── raspberry_pi/              # Raspberry Pi sensor/camera scripts (deployed on .28)
│   ├── app.py                         # Flask web interface (port 8080)
│   ├── mqtt_publisher.py              # Publishes all sensor data to MQTT
│   ├── metadata_updater.py            # Updates /tmp/camera_metadata.json
│   ├── camera_metadata_writer.py      # Writes camera stream to file
│   ├── camera_monitor.py              # Camera monitoring service
│   ├── start_csi_with_metadata.sh     # Starts CSI camera with metadata output
│   ├── config/
│   │   ├── mediamtx.yml               # MediaMTX streaming server config
│   │   └── start_usb_camera.sh        # USB camera startup script
│   ├── static/                        # Web interface assets
│   └── templates/                     # Flask HTML templates
│
├── config/                    # Shared configuration files
│   ├── mediamtx.yml                   # MediaMTX config (reference)
│   └── start_usb_camera.sh
│
├── standalone_viewer.html     # Standalone camera viewer
├── app.py                     # Flask app (local development)
├── static/                    # Local static files
└── templates/                 # Local templates
```

## Production Deployment Map

### Server: YOUR_MQTT_BROKER_IP (Docker Stack)
**Services**: MQTT Broker, InfluxDB, Telegraf, Grafana

**Deployed Location**: `/home/YOUR_PI_USERNAME/beeperKeeper/`

**Running Services**:
- `beeper_mqtt` (mosquitto:2.0.22) - Ports 1883, 9001
- `beeper_influxdb` (influxdb:2.7-alpine) - Port 8086
- `beeper_telegraf` (telegraf:1.36-alpine)
- `beeper_grafana` (grafana:12.2.1) - Port 3000

**Key Configuration**:
- Grafana Admin: `admin / beeperkeeper`
- InfluxDB Org: `beeperkeeper`
- InfluxDB Bucket: `sensors`
- SMTP: Configured via environment variables in docker-compose.yml

### Server: YOUR_PI_IP (Raspberry Pi 5)
**Services**: Sensor Collection, Camera Streaming, Web Interface

**Deployed Location**: `/opt/beeperKeeper/`

**Running Services**:
- MediaMTX streaming server (ports 8888 HLS, 8554 RTSP, 9997 API)
- Flask web interface (port 8080)
- mqtt_publisher.py (publishes sensor data every 10s)
- metadata_updater.py (updates camera metadata continuously)
- rpicam-vid (CSI camera streaming)
- ffmpeg (USB camera streaming)

**Hardware**:
- BME680 environmental sensor (I2C)
- OV5647 CSI camera (IR night vision) - 800x600 @ 15fps
- Logitech C270 USB webcam - 640x480 @ 15fps

## Data Flow

```
Sensors (BME680, CPU, Camera)
    ↓
mqtt_publisher.py (every 10s)
    ↓
MQTT Broker (mosquitto on .7)
    ↓
Telegraf (subscribes to topics)
    ↓
InfluxDB (sensors bucket)
    ↓
Grafana (visualization + alerts)
```

## Camera Streaming Architecture

```
CSI Camera (OV5647) → rpicam-vid (with metadata) → metadata stream file
                                                  ↓
metadata_updater.py reads stream → /tmp/camera_metadata.json
                                                  ↓
                        mqtt_publisher.py → MQTT → InfluxDB → Grafana
                                 |
rpicam-vid H.264 output → ffmpeg → RTSP → MediaMTX → HLS
                                                      ↓
                                    http://YOUR_PI_IP:8888/csi_camera/


USB Camera (C270) → ffmpeg (H.264 + Opus audio) → RTSP → MediaMTX → HLS
                                                                      ↓
                                              http://YOUR_PI_IP:8888/usb_camera/
```

## MQTT Topics

### BME680 Environmental Sensor
- `beeper/sensors/bme680/all` - All BME680 data in one message
  - Fields: temperature, humidity, pressure, gas_raw, iaq, co2_equivalent

### System Metrics
- `beeper/system/cpu_percent` - CPU usage percentage (field: value)
- `beeper/system/memory_percent` - Memory usage percentage (field: value)
- `beeper/system/disk_percent` - Disk usage percentage (field: value)
- `beeper/sensors/cpu/temperature` - CPU temperature (field: cpu_temp)

### Camera Metadata
- `beeper/camera/csi/metadata` - CSI camera metadata
  - Fields (CamelCase): ExposureTime, AnalogueGain, Lux, ColourTemperature, DigitalGain, AeState, AfState, FocusFoM
- `beeper/camera/usb/metadata` - USB camera metadata (if applicable)

## Deployment Instructions

### Deploy to YOUR_MQTT_BROKER_IP (Docker Stack)

```bash
# SSH to server
ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP

# Navigate to deployment directory
cd /home/YOUR_PI_USERNAME/beeperKeeper

# Update configuration files (if changed)
# Copy updated files from v2_0/docker/ to respective locations

# Restart stack
docker-compose down
docker-compose up -d

# Verify services
docker-compose ps
docker logs beeper_grafana --tail 50
docker logs beeper_telegraf --tail 50
```

### Deploy to YOUR_PI_IP (Raspberry Pi)

```bash
# SSH to Raspberry Pi
ssh YOUR_PI_USERNAME@YOUR_PI_IP

# Navigate to deployment directory
cd /opt/beeperKeeper

# Update Python scripts (if changed)
# Copy updated files from v2_0/raspberry_pi/ to /opt/beeperKeeper/

# Restart services
sudo systemctl restart mediamtx
pkill -f mqtt_publisher.py
pkill -f metadata_updater.py
pkill -f app.py

# Start services
cd /opt/beeperKeeper
nohup python3 mqtt_publisher.py > /tmp/mqtt_publisher.log 2>&1 &
nohup python3 metadata_updater.py > /tmp/metadata_updater.log 2>&1 &
nohup python3 app.py > /tmp/flask_app.log 2>&1 &

# Verify MediaMTX streams
curl http://localhost:9997/v3/paths/list | python3 -m json.tool
```

## Configuration Updates

### Update Grafana Dashboard

1. Edit `docker/grafana/dashboards/beeper_sensors.json` locally
2. Upload to server:
   ```bash
   scp docker/grafana/dashboards/beeper_sensors.json YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/grafana/dashboards/
   ```
3. Grafana auto-reloads provisioned dashboards (may take 30-60s)

### Update Alert Rules

1. Edit `docker/grafana/provisioning/alerting/rules.yaml`
2. Upload to server:
   ```bash
   scp docker/grafana/provisioning/alerting/rules.yaml YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/grafana/provisioning/alerting/
   ```
3. Restart Grafana:
   ```bash
   ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker restart beeper_grafana"
   ```

### Update Telegraf Configuration

1. Edit `docker/telegraf/telegraf.conf`
2. Upload and restart:
   ```bash
   scp docker/telegraf/telegraf.conf YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/telegraf/
   ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker restart beeper_telegraf"
   ```

### Update Raspberry Pi Scripts

1. Edit scripts in `raspberry_pi/`
2. Upload to Pi:
   ```bash
   scp raspberry_pi/mqtt_publisher.py YOUR_PI_USERNAME@YOUR_PI_IP:/opt/beeperKeeper/
   ```
3. Restart affected services (see deployment instructions above)

## Important Notes

### v1 vs v2 Separation
- **v1 Location**: `/home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/` (root)
- **v2 Location**: `/home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/v2_0/`
- **DO NOT** commingle files between v1 and v2
- v2 is the active development/deployment directory

### Camera Stream URLs
- **CSI Camera (IR)**: http://YOUR_PI_IP:8888/csi_camera/
- **USB Camera**: http://YOUR_PI_IP:8888/usb_camera/
- **Port**: 8888 (HLS), not 8889

### Dashboard Version Tracking
- Current deployed version: 75+
- Update version number in dashboard JSON when making changes
- Check Grafana UI for actual deployed version

### Alert Management
- File-provisioned alerts persist in Grafana database
- To delete: Must remove from YAML AND delete from database
- Database path: `/var/lib/grafana/grafana.db` (in container)

### Camera Metadata Behavior
- Static exposure time in stable lighting is CORRECT behavior
- AeState=2 means auto-exposure CONVERGED (locked optimal settings)
- Lux values should vary normally even when exposure is static
- If camera metadata stops updating, check metadata_updater.py process

## Troubleshooting

### No Data in Grafana Panels
1. Check MQTT broker has messages: `ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker exec -it beeper_mqtt mosquitto_sub -t 'beeper/#' -C 5"`
2. Check InfluxDB has data: `ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker exec -it beeper_influxdb influx query 'from(bucket:\"sensors\") |> range(start: -5m) |> limit(n:5)'"`
3. Verify Telegraf is running: `ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker logs beeper_telegraf --tail 50"`
4. Check dashboard query field filters match InfluxDB field names

### Camera Streams Not Working
1. Verify MediaMTX is running: `ssh YOUR_PI_USERNAME@YOUR_PI_IP "curl http://localhost:9997/v3/paths/list"`
2. Check stream paths: Should see `csi_camera` and `usb_camera` with `ready: true`
3. Test HLS access: `curl -I http://YOUR_PI_IP:8888/csi_camera/`
4. Check camera processes: `ssh YOUR_PI_USERNAME@YOUR_PI_IP "ps aux | grep rpicam"`

### MQTT Publisher Not Running
1. Check process: `ssh YOUR_PI_USERNAME@YOUR_PI_IP "ps aux | grep mqtt_publisher"`
2. Check logs: `ssh YOUR_PI_USERNAME@YOUR_PI_IP "tail -50 /tmp/mqtt_publisher.log"`
3. Restart: See deployment instructions above

### Alerts Not Firing/Sending
1. Check alert rules loaded: Grafana UI → Alerting → Alert Rules
2. Check contact points configured: Grafana UI → Alerting → Contact Points
3. Verify SMTP settings in docker-compose.yml
4. Check Grafana logs: `ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker logs beeper_grafana | grep -i alert"`

## Access Information

### Grafana
- **URL**: http://YOUR_MQTT_BROKER_IP:3000
- **Username**: admin
- **Password**: beeperkeeper

### InfluxDB
- **URL**: http://YOUR_MQTT_BROKER_IP:8086
- **Organization**: beeperkeeper
- **Bucket**: sensors
- **Token**: beeper-admin-token-change-this-in-production

### MQTT Broker
- **Host**: YOUR_MQTT_BROKER_IP
- **Port**: 1883 (MQTT), 9001 (WebSocket)
- **No authentication** (internal network only)

### Raspberry Pi Web Interface
- **URL**: http://YOUR_PI_IP:8080
- Shows live sensor readings and system info

### MediaMTX
- **HLS Streams**: http://YOUR_PI_IP:8888
- **RTSP**: rtsp://YOUR_PI_IP:8554
- **API**: http://YOUR_PI_IP:9997

## Recent Changes

### 2025-10-25
- Fixed camera stream links in dashboard (port 8889 → 8888)
- Updated dashboard with 10 real-world lux thresholds
- Fixed all panel queries to include proper field filters
- Removed test_email_template alert that was firing continuously
- Downloaded all deployed configs to v2_0 directory
- Organized v2_0 directory structure with docker/ subdirectory
- Updated docker-compose.yml volume paths for v2 structure
- Created this deployment guide

---

**Last Updated**: 2025-10-25
**Maintained By**: Claude Code
**Production Servers**: YOUR_MQTT_BROKER_IP (Docker), YOUR_PI_IP (Raspberry Pi)
