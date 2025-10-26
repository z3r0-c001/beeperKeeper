# BeeperKeeper v2.0 Deployment Guide

## Quick Start

### 1. Backend Deployment
```bash
# Install dependencies
pip3 install flask paho-mqtt psutil requests pyjwt

# Copy app.py to server
scp backend/app.py USERNAME@FLASK_SERVER_IP:/opt/APPNAME/

# Update configuration in app.py:
MQTT_BROKER = "YOUR_MQTT_BROKER_IP"
MQTT_PORT = 1883

# Start Flask app
cd /opt/APPNAME
nohup python3 app.py > /tmp/flask.log 2>&1 &
```

### 2. Frontend Deployment
```bash
# Copy template
scp frontend/index.html USERNAME@FLASK_SERVER_IP:/opt/APPNAME/templates/

# Restart Flask app
pkill -f 'python3.*app.py'
cd /opt/APPNAME && nohup python3 app.py > /tmp/flask.log 2>&1 &
```

### 3. Metadata Updater
```bash
# Copy script
scp scripts/metadata_updater.py USERNAME@FLASK_SERVER_IP:/opt/APPNAME/

# Start service
cd /opt/APPNAME
nohup python3 metadata_updater.py > /tmp/metadata_updater.log 2>&1 &
```

## Configuration

### Required Services
- MQTT Broker (Mosquitto)
- InfluxDB v2
- Grafana
- MediaMTX (HLS streaming)

### Environment
- Python 3.8+
- Flask web server
- Cloudflare Access (for JWT authentication)

## Verification
```bash
# Check Flask app
curl http://FLASK_SERVER_IP:8080/api/metrics

# Check whoami endpoint
curl http://FLASK_SERVER_IP:8080/api/whoami

# Check chat messages
curl http://FLASK_SERVER_IP:8080/api/chat/messages

# Check processes
ps aux | grep -E 'app.py|metadata_updater'
```
