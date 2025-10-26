# Migration from v1 to v2 - Directory Cleanup Guide

**Status:** v2.0 is fully deployed and operational
**Date:** October 25, 2025

---

## Current State

### Production Deployment (/opt/beeperKeeper/ on Pi)
**✅ This is v2.0 code** - fully operational

```
/opt/beeperKeeper/
├── app.py                          # Flask app with user tracking & chat
├── templates/
│   └── index.html                  # WebRTC/HLS hybrid UI with teal borders
├── static/images/
│   ├── chicken_of_despair.png
│   └── tinyWaxer.png
├── config/
│   ├── mediamtx.yml                # RTSP/HLS/WebRTC config
│   ├── start_csi_camera.sh         # 800x600 @ 15fps hardware H.264
│   └── start_usb_camera.sh         # 640x480 @ 10fps YUYV → H.264 + Opus
├── metadata_updater.py             # Optimized (0.2% CPU)
├── rotate_camera_logs.sh           # Log rotation cron job
├── mqtt_publisher.py               # Sensor data publisher
└── camera_monitor.py               # Legacy (not in use)
```

### Development Repository (/home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/)

#### v2_0/ Directory (Current Source of Truth)
**✅ Keep This - All Current Code**

```
v2_0/
├── raspberry_pi/                   # Source code deployed to Pi
│   ├── app.py                      # Main Flask application
│   ├── templates/index.html        # Web UI
│   ├── config/                     # Camera & MediaMTX configs
│   └── *.py                        # Helper scripts
├── docker/                         # Monitoring server configs
│   ├── grafana/dashboards/         # Dashboard JSON
│   └── ...
├── ARCHITECTURE.md                 # System design
├── README.md                       # Project overview
├── V2_DEPLOYMENT_GUIDE.md          # Deployment procedures
├── V2_PRODUCTION_NOTES.md          # Complete production documentation
└── V2_SYNC_STATUS.md              # Sync tracking
```

**Status:** ✅ **KEEP** - This is the current, maintained codebase

---

#### Old Root Directory Files (Outdated v1 Documentation)
**⚠️ Can Be Archived/Deleted**

```
/beeperKeeper/ (root)
├── ALERT_SETUP.md                  # v1 alert documentation (outdated)
├── AUDIT.md                        # v1 system audit (outdated)
├── AUDIT_SUMMARY.md                # v1 audit summary (outdated)
├── BEEPER_KEEPER_IMPROVEMENTS.md   # v1 improvement notes (outdated)
├── BME680_AIR_QUALITY_GUIDE.md     # Still relevant (sensor info)
├── BME680_ENHANCEMENTS_SUMMARY.md  # v1 enhancements (outdated)
├── BME680_QUICK_REFERENCE.md       # Still relevant (sensor reference)
├── CLOUDFLARE_ACCESS_SETUP.md      # Still relevant (access config)
├── CREDENTIALS.md                  # Still relevant (credentials)
├── DEPLOYMENT.md                   # v1 deployment (superseded by v2_0/V2_DEPLOYMENT_GUIDE.md)
├── DEPLOYMENT_SUMMARY.md           # v1 deployment summary (outdated)
├── FINAL_AUDIT_AND_STATUS.md       # v1 final audit (outdated)
├── GRAFANA_SETUP.md                # v1 Grafana setup (partially outdated)
├── IMPROVEMENT_PRIORITIES.md       # v1 priorities (completed in v2)
├── INSTALLATION.md                 # v1 installation (superseded by v2 docs)
├── LICENSE                         # Still relevant
├── POWER_DIAGNOSTICS.md            # v1 power diagnostics (outdated)
├── README.md                       # v1 README (superseded by v2_0/README.md)
├── STREAMING_*.md                  # v1 streaming analysis (outdated)
├── chicken_of_despair.png          # Duplicate (exists in v2_0)
├── docker/                         # v1 Docker configs (outdated)
├── grafana/                        # v1 Grafana configs (moved to v2_0/docker/)
├── images/                         # v1 images (duplicates)
├── mosquitto/                      # v1 MQTT config (still in use on .7 server)
└── telegraf/                       # v1 Telegraf config (still in use on .7 server)
```

---

## Recommended Actions

### Keep (Still Relevant)
- ✅ `LICENSE` - Project license
- ✅ `CREDENTIALS.md` - System credentials
- ✅ `CLOUDFLARE_ACCESS_SETUP.md` - Cloudflare tunnel configuration
- ✅ `BME680_AIR_QUALITY_GUIDE.md` - Sensor reference documentation
- ✅ `BME680_QUICK_REFERENCE.md` - Sensor quick reference
- ✅ `mosquitto/` - MQTT broker config (running on .7 server)
- ✅ `telegraf/` - Telegraf config (running on .7 server)

### Archive (Historical Reference)
Create an `archive/v1/` directory and move:
- ⏸️ All v1 deployment documentation
- ⏸️ All v1 audit/improvement documents
- ⏸️ Old Grafana/Docker configs
- ⏸️ v1 streaming analysis documents

### Delete (Duplicates/Superseded)
- ❌ `chicken_of_despair.png` (duplicate - exists in v2_0)
- ❌ `images/` directory (duplicates)
- ❌ `grafana/` directory (superseded by v2_0/docker/grafana/)
- ❌ Old `docker/` directory (if different from v2_0/docker/)

---

## Migration Command Suggestions

```bash
# Navigate to beeperKeeper root
cd /home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/

# Create archive directory
mkdir -p archive/v1/

# Move v1 documentation to archive
mv ALERT_SETUP.md archive/v1/
mv AUDIT.md archive/v1/
mv AUDIT_SUMMARY.md archive/v1/
mv BEEPER_KEEPER_IMPROVEMENTS.md archive/v1/
mv BME680_ENHANCEMENTS_SUMMARY.md archive/v1/
mv DEPLOYMENT.md archive/v1/
mv DEPLOYMENT_SUMMARY.md archive/v1/
mv FINAL_AUDIT_AND_STATUS.md archive/v1/
mv GRAFANA_SETUP.md archive/v1/
mv IMPROVEMENT_PRIORITIES.md archive/v1/
mv INSTALLATION.md archive/v1/
mv POWER_DIAGNOSTICS.md archive/v1/
mv STREAMING_*.md archive/v1/
mv README.md archive/v1/README_v1.md

# Remove duplicates
rm chicken_of_despair.png
rm -rf images/
rm -rf grafana/  # If different from v2_0/docker/grafana/

# Keep only essential root files
# Keep: LICENSE, CREDENTIALS.md, CLOUDFLARE_ACCESS_SETUP.md
# Keep: BME680_AIR_QUALITY_GUIDE.md, BME680_QUICK_REFERENCE.md
# Keep: mosquitto/, telegraf/ (still used on .7 server)
# Keep: v2_0/ (primary codebase)
```

---

## Final Structure After Cleanup

```
/home/YOUR_DEV_USERNAME/codeOne/beeperKeeper/
├── v2_0/                           # ✅ PRIMARY CODEBASE
│   ├── raspberry_pi/               # Production code
│   ├── docker/                     # Monitoring configs
│   └── *.md                        # Current documentation
├── archive/                        # Historical reference
│   └── v1/                         # Archived v1 docs
├── mosquitto/                      # MQTT broker config (in use)
├── telegraf/                       # Telegraf config (in use)
├── LICENSE                         # Project license
├── CREDENTIALS.md                  # System credentials
├── CLOUDFLARE_ACCESS_SETUP.md      # Cloudflare config
├── BME680_AIR_QUALITY_GUIDE.md     # Sensor reference
└── BME680_QUICK_REFERENCE.md       # Sensor quick ref
```

---

## Summary

**Answer to your question:**

> "do we still need anything in the old root directory /beeperKeeper or is everything we need /beeperKeeper/v2_0"

**Short Answer:** Everything you need is in `/beeperKeeper/v2_0/`. The old root directory contains:
- ✅ **Still needed:** mosquitto/, telegraf/, a few credential/config docs
- ⏸️ **Archive:** All v1 documentation (outdated but historical)
- ❌ **Delete:** Duplicate images and old configs

**Recommendation:**
1. Archive v1 docs to `archive/v1/`
2. Keep mosquitto/ and telegraf/ configs (running on .7 server)
3. Keep credential/reference docs at root level
4. **v2_0/ is the source of truth** for all active code and current documentation

---

**Document Version:** 1.0
**Last Updated:** October 25, 2025
