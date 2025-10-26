# BeeperKeeper v2.0 - Development Files

Sanitized source code and documentation for the BeeperKeeper chicken coop monitoring system.

## Structure
```
├── backend/          - Flask application (app.py)
├── frontend/         - HTML templates (index.html)
├── scripts/          - Helper scripts (metadata_updater.py)
├── docs/             - Documentation
│   ├── CHANGELOG.md  - Recent changes
│   └── DEPLOYMENT.md - Deployment guide
└── beeper_sensors.json - Grafana dashboard
```

## Recent Updates (2025-10-26)

### ✅ Chat Message Deletion
Users can now delete their own chat messages with ownership verification.

### ✅ Camera Metadata Fixed
Metadata pipeline now operational (Exposure, Lux, Color Temp, Gain).

### ✅ Dashboard Cleanup
Removed duplicate dashboards, optimized layout.

## Key Features
- Real-time sensor monitoring (BME680)
- Dual camera HLS streaming (CSI + USB with audio)
- Chat system with message deletion
- Active user tracking
- Camera metadata collection
- Grafana dashboards
- MQTT integration

## Sanitization
All IP addresses, usernames, and paths have been sanitized:
- `172.16.0.x` → `MQTT_BROKER_IP` / `FLASK_SERVER_IP`
- `/home/binhex/` → `/home/USERNAME/`
- `/opt/beeperKeeper/` → `/opt/APPNAME/`

Replace placeholders with your actual values before deployment.
