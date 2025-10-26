# v2.0 Sync Status

## Overview
This document tracks the synchronization status between the v2_0 local directory and the deployed production servers.

**Last Full Sync**: 2025-10-25 17:30

## Directory Structure Differences

### v2_0 Local vs Production

**v2_0 Structure** (Development/Reference):
```
v2_0/
├── docker/                    # All Docker service configs organized here
│   ├── grafana/
│   ├── mosquitto/
│   └── telegraf/
├── raspberry_pi/              # All Raspberry Pi scripts
├── images/                    # Shared images
└── docker-compose.yml         # References ./docker/* paths
```

**Production .7 Structure** (Deployed):
```
/home/YOUR_PI_USERNAME/beeperKeeper/
├── grafana/                   # No "docker/" parent directory
├── mosquitto/
├── telegraf/
├── chicken_of_despair.png     # Images in root
└── docker-compose.yml         # References ./grafana, ./mosquitto, etc.
```

**Production .28 Structure** (Deployed):
```
/opt/beeperKeeper/
├── *.py                       # Python scripts directly in root
├── config/
├── static/
└── templates/
```

## File Synchronization Status

### ✅ Fully Synced (Downloaded from Production → v2_0)

#### From YOUR_MQTT_BROKER_IP (.7 server)
- [x] docker-compose.yml → `./docker-compose.yml` (MODIFIED for v2 paths)
- [x] .env.example → `./.env.example`
- [x] grafana/provisioning/alerting/* → `./docker/grafana/provisioning/alerting/`
- [x] grafana/provisioning/dashboards/* → `./docker/grafana/provisioning/dashboards/`
- [x] grafana/provisioning/datasources/* → `./docker/grafana/provisioning/datasources/`
- [x] grafana/dashboards/beeper_sensors.json → `./docker/grafana/dashboards/beeper_sensors.json`
- [x] grafana/grafana.ini → `./docker/grafana/grafana.ini`
- [x] grafana/templates/* → `./docker/grafana/templates/`
- [x] grafana/public/custom.css → `./docker/grafana/public/custom.css`
- [x] telegraf/telegraf.conf → `./docker/telegraf/telegraf.conf`
- [x] mosquitto/config/mosquitto.conf → `./docker/mosquitto/config/mosquitto.conf`
- [x] chicken_of_despair*.png → `./images/`
- [x] good_supply_logo*.png → `./images/`

#### From YOUR_PI_IP (.28 Raspberry Pi)
- [x] /opt/beeperKeeper/*.py → `./raspberry_pi/`
  - app.py
  - mqtt_publisher.py
  - metadata_updater.py
  - camera_metadata_writer.py
  - camera_monitor.py
  - config.py
- [x] /opt/beeperKeeper/*.sh → `./raspberry_pi/`
  - start_csi_with_metadata.sh
- [x] /opt/beeperKeeper/config/* → `./raspberry_pi/config/`
  - mediamtx.yml
  - start_usb_camera.sh
- [x] /opt/beeperKeeper/templates/* → `./raspberry_pi/templates/`
- [x] /opt/beeperKeeper/static/* → `./raspberry_pi/static/`

### ⚠️ Modified in v2_0 (Not Yet Pushed to Production)

#### Modified Files
- `docker-compose.yml`
  - **Change**: Updated volume paths from `./grafana` to `./docker/grafana`, etc.
  - **Reason**: v2_0 uses organized directory structure
  - **Action Required**: DO NOT push this to production - it's a local reference version

- `docker/grafana/dashboards/beeper_sensors.json`
  - **Change**: Fixed camera stream links (port 8889 → 8888)
  - **Status**: ✅ PUSHED to production on 2025-10-25 17:25
  - **Deployed**: Yes

### 📋 Files in v2_0 Not in Production

#### Development/Reference Files
- `V2_DEPLOYMENT_GUIDE.md` - This deployment guide (local documentation)
- `V2_SYNC_STATUS.md` - This sync status (local documentation)
- `ARCHITECTURE.md` - Architecture documentation (local)
- `README.md` - Project README (local)
- `app.py` (root) - Duplicate of raspberry_pi/app.py (for reference)
- `standalone_viewer.html` - Standalone viewer (development tool)
- `config/` (root) - Reference configs (mediamtx.yml, etc.)
- `static/` (root) - Development static files
- `templates/` (root) - Development templates

## Deployment Workflows

### Deploying v2_0 Changes to Production

#### To .7 Server (Docker Stack)

**⚠️ IMPORTANT**: The production .7 server uses a DIFFERENT directory structure than v2_0. Volume paths in production docker-compose.yml reference `./grafana`, `./telegraf`, etc. (no `docker/` prefix).

```bash
# Deploy Grafana dashboard changes
scp docker/grafana/dashboards/beeper_sensors.json \
    YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/grafana/dashboards/

# Deploy Grafana config changes
scp docker/grafana/grafana.ini \
    YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/grafana/

# Deploy Telegraf config changes
scp docker/telegraf/telegraf.conf \
    YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/telegraf/

# Deploy alert rule changes
scp docker/grafana/provisioning/alerting/rules.yaml \
    YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/grafana/provisioning/alerting/

# Restart specific service (if needed)
ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "docker restart beeper_grafana"
```

#### To .28 Raspberry Pi

```bash
# Deploy Python script changes
scp raspberry_pi/mqtt_publisher.py \
    YOUR_PI_USERNAME@YOUR_PI_IP:/opt/beeperKeeper/

scp raspberry_pi/metadata_updater.py \
    YOUR_PI_USERNAME@YOUR_PI_IP:/opt/beeperKeeper/

# Deploy MediaMTX config
scp raspberry_pi/config/mediamtx.yml \
    YOUR_PI_USERNAME@YOUR_PI_IP:/opt/beeperKeeper/config/

# Restart services
ssh YOUR_PI_USERNAME@YOUR_PI_IP "pkill -f mqtt_publisher.py && \
    cd /opt/beeperKeeper && \
    nohup python3 mqtt_publisher.py > /tmp/mqtt_publisher.log 2>&1 &"
```

### Syncing Production Changes to v2_0

If changes are made directly on production servers (NOT recommended), sync them back:

```bash
# From .7 server
cd /home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/v2_0
scp YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP:/home/YOUR_PI_USERNAME/beeperKeeper/grafana/dashboards/beeper_sensors.json \
    docker/grafana/dashboards/

# From .28 server
scp YOUR_PI_USERNAME@YOUR_PI_IP:/opt/beeperKeeper/mqtt_publisher.py \
    raspberry_pi/
```

## Key Differences to Remember

### Docker Compose Volume Paths

**v2_0 Local** (for reference/development):
```yaml
volumes:
  - ./docker/grafana/provisioning:/etc/grafana/provisioning
  - ./docker/telegraf/telegraf.conf:/etc/telegraf/telegraf.conf
  - ./images/chicken_of_despair.png:/usr/share/grafana/public/img/chicken_of_despair.png
```

**Production .7** (actually deployed):
```yaml
volumes:
  - ./grafana/provisioning:/etc/grafana/provisioning
  - ./telegraf/telegraf.conf:/etc/telegraf/telegraf.conf
  - ./chicken_of_despair.png:/usr/share/grafana/public/img/chicken_of_despair.png
```

### MediaMTX Config Differences

**v2_0 Local** (`config/mediamtx.yml` - older reference):
```yaml
csi_camera:
  runOnInit: bash -c 'rpicam-vid --codec h264 ...'
```

**Production .28** (`raspberry_pi/config/mediamtx.yml` - actually deployed):
```yaml
csi_camera:
  runOnInit: /opt/beeperKeeper/start_csi_with_metadata.sh
```

The raspberry_pi version is the CORRECT deployed version.

## Sync Best Practices

1. **Always edit in v2_0 first** - Make changes locally, test, then deploy
2. **Account for path differences** - Remember v2_0 uses `docker/` subdirectory
3. **Test before deploying** - Use local Docker stack if possible
4. **Document changes** - Update this file when deploying to production
5. **Keep sync records** - Note what was deployed and when

## Recent Deployments

| Date | File | Direction | Notes |
|------|------|-----------|-------|
| 2025-10-25 17:25 | beeper_sensors.json | v2 → .7 | Fixed camera stream URLs (8889→8888) |
| 2025-10-25 17:21 | All configs | .7,.28 → v2 | Initial full sync to v2_0 |

## Verification Commands

### Check Production .7 Files
```bash
ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "ls -lah /home/YOUR_PI_USERNAME/beeperKeeper/"
ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "md5sum /home/YOUR_PI_USERNAME/beeperKeeper/grafana/dashboards/beeper_sensors.json"
```

### Check Production .28 Files
```bash
ssh YOUR_PI_USERNAME@YOUR_PI_IP "ls -lah /opt/beeperKeeper/"
ssh YOUR_PI_USERNAME@YOUR_PI_IP "md5sum /opt/beeperKeeper/mqtt_publisher.py"
```

### Compare Local vs Production
```bash
# Compare dashboard file
md5sum docker/grafana/dashboards/beeper_sensors.json
ssh YOUR_PI_USERNAME@YOUR_MQTT_BROKER_IP "md5sum /home/YOUR_PI_USERNAME/beeperKeeper/grafana/dashboards/beeper_sensors.json"

# Compare MQTT publisher
md5sum raspberry_pi/mqtt_publisher.py
ssh YOUR_PI_USERNAME@YOUR_PI_IP "md5sum /opt/beeperKeeper/mqtt_publisher.py"
```

---

**Last Updated**: 2025-10-25 17:30
**Next Sync Review**: As needed when deploying changes
