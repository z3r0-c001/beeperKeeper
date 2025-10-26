# Beeper Keeper v2.0 - Placeholder Configuration Guide

**⚠️ IMPORTANT:** This repository contains **sanitized code** with placeholders. You MUST replace these placeholders with your actual values before deployment.

---

## Quick Reference Table

| Placeholder | Replace With | Example | Where Used |
|------------|--------------|---------|------------|
| `YOUR_MQTT_BROKER_IP` | Your MQTT broker's IP address | `192.168.1.10` | Python files, configs, docs |
| `YOUR_PI_IP` | Your Raspberry Pi's IP address | `192.168.1.20` | Python files, configs, docs |
| `CLIENT_IP_EXAMPLE` | Example client IP (usually leave as-is) | `192.168.1.50` | Documentation only |
| `YOUR_DOMAIN` | Your public domain name | `camera.yourdomain.com` | Flask app, docs |
| `YOUR_BASE_DOMAIN` | Your base domain | `yourdomain.com` | Documentation |
| `YOUR_HOSTNAME` | Your Raspberry Pi hostname | `raspberrypi` | System configs |
| `YOUR_PI_USERNAME` | SSH username for Raspberry Pi | `pi` | Deployment scripts, docs |
| `YOUR_DEV_USERNAME` | Your dev machine username | `yourname` | Deployment scripts |
| `YOUR_GITHUB_USERNAME` | Your GitHub username | `yourusername` | Documentation |
| `example_user` | Example user for docs | `alice` | Documentation examples |
| `your-email@gmail.com` | Your email for alerts | `you@example.com` | Grafana SMTP config |

---

## Detailed Configuration Guide

### 1. Network Configuration

#### MQTT Broker IP (`YOUR_MQTT_BROKER_IP`)

**Files to Update:**
- `raspberry_pi/app.py` (line 24)
- `raspberry_pi/mqtt_publisher.py`
- `docker/telegraf/telegraf.conf`
- All documentation files

**Find:**
```python
MQTT_BROKER = "YOUR_MQTT_BROKER_IP"
```

**Replace with:**
```python
MQTT_BROKER = "192.168.1.10"  # Your MQTT broker IP
```

**What is this?**
- The IP address of the server running Mosquitto MQTT broker
- This is typically your monitoring server
- Must be accessible from the Raspberry Pi

---

#### Raspberry Pi IP (`YOUR_PI_IP`)

**Files to Update:**
- All documentation files (README.md, V2_PRODUCTION_NOTES.md, etc.)
- `raspberry_pi/templates/index.html`
- `docker/grafana/dashboards/beeper_sensors.json`

**Find:**
```
http://YOUR_PI_IP:8080
```

**Replace with:**
```
http://192.168.1.20:8080  # Your Pi's IP
```

**What is this?**
- The static IP address of your Raspberry Pi running the camera system
- Used for local network access to the web interface
- Should be reserved in your DHCP server

---

### 2. Domain Configuration

#### Public Domain (`YOUR_DOMAIN`)

**Files to Update:**
- `raspberry_pi/app.py` (line 179)
- `raspberry_pi/templates/index.html` (line 346)
- All documentation

**Find:**
```python
if 'YOUR_DOMAIN' in host:
```

**Replace with:**
```python
if 'camera.yourdomain.com' in host:
```

**What is this?**
- Your Cloudflare Tunnel domain (if using Cloudflare Access)
- Public-facing URL for remote access
- Optional - only needed if using Cloudflare tunnel

---

### 3. Hostname Configuration

#### Raspberry Pi Hostname (`YOUR_HOSTNAME`)

**Files to Update:**
- Documentation files only (appears in logs/examples)

**Find:**
```
YOUR_HOSTNAME systemd[1]: Started...
```

**Replace with:**
```
raspberrypi systemd[1]: Started...
```

**What is this?**
- The hostname of your Raspberry Pi (set via `sudo raspi-config`)
- Appears in system logs
- Not critical to change for functionality

---

### 4. Username Configuration

#### Pi SSH Username (`YOUR_PI_USERNAME`)

**Files to Update:**
- `V2_DEPLOYMENT_GUIDE.md`
- Any deployment scripts

**Find:**
```bash
ssh YOUR_PI_USERNAME@YOUR_PI_IP
```

**Replace with:**
```bash
ssh pi@192.168.1.20
```

**What is this?**
- The username you use to SSH into the Raspberry Pi
- Default is usually `pi` but may be custom
- Used in all deployment/SCP commands

---

### 5. Email Configuration (Optional)

#### Grafana Email Alerts

**Files to Update:**
- `docker-compose.yml` (SMTP settings)
- `.env` file (create if doesn't exist)

**Find:**
```yaml
- GF_SMTP_USER=${GF_SMTP_USER:-your-email@gmail.com}
```

**Replace with:**
```yaml
- GF_SMTP_USER=${GF_SMTP_USER:-alerts@yourdomain.com}
```

**What is this?**
- Email address for sending Grafana alerts
- Requires SMTP server configuration
- Optional - only needed if you want email alerts

---

## Step-by-Step Setup

### Step 1: Clone Repository
```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/beeperKeeper.git
cd beeperKeeper
```

### Step 2: Find and Replace (Quick Method)

Create a file called `my_config.txt` with your values:
```
MY_MQTT_IP=192.168.1.10
MY_PI_IP=192.168.1.20
MY_DOMAIN=camera.yourdomain.com
MY_USERNAME=pi
```

Then run this script to replace all placeholders:
```bash
#!/bin/bash
source my_config.txt

find . -type f \( -name "*.py" -o -name "*.yml" -o -name "*.yaml" -o -name "*.conf" \) \
  -exec sed -i "s/YOUR_MQTT_BROKER_IP/$MY_MQTT_IP/g" {} \; \
  -exec sed -i "s/YOUR_PI_IP/$MY_PI_IP/g" {} \; \
  -exec sed -i "s/YOUR_DOMAIN/$MY_DOMAIN/g" {} \; \
  -exec sed -i "s/YOUR_PI_USERNAME/$MY_USERNAME/g" {} \;

echo "Placeholders replaced!"
```

### Step 3: Verify Replacements

Check that all placeholders are replaced:
```bash
grep -r "YOUR_" --include="*.py" --include="*.yml" --include="*.conf" .
```

This should return ZERO results. If you see any "YOUR_" strings, you missed some placeholders.

### Step 4: Deploy to Raspberry Pi

Follow the deployment guide in `V2_DEPLOYMENT_GUIDE.md` with your actual values.

---

## Files Requiring Manual Configuration

These files contain placeholders that MUST be updated:

### Critical (Won't work without these)
- ✅ `raspberry_pi/app.py` - MQTT broker IP
- ✅ `docker/telegraf/telegraf.conf` - MQTT broker IP
- ✅ `docker/mosquitto/config/mosquitto.conf` - Network settings

### Important (Affects functionality)
- ⚠️ `raspberry_pi/templates/index.html` - Domain detection
- ⚠️ `docker/grafana/dashboards/beeper_sensors.json` - Camera links

### Documentation Only (Optional)
- 📝 All `.md` files - Update for your reference
- 📝 Example commands - Update IPs for copy/paste

---

## Network Diagram (Your Setup)

Replace this with your actual network:

```
┌─────────────────────────────────────┐
│ YOUR_MQTT_BROKER_IP (192.168.1.10) │
│ - Mosquitto MQTT                    │
│ - Telegraf                          │
│ - InfluxDB                          │
│ - Grafana                           │
└─────────────────────────────────────┘
                 │
                 │ MQTT Port 1883
                 │
                 ▼
┌─────────────────────────────────────┐
│ YOUR_PI_IP (192.168.1.20)          │
│ - Flask Web App (Port 8080)        │
│ - MediaMTX (Ports 8554/8888/8889)  │
│ - Camera Capture                    │
└─────────────────────────────────────┘
```

---

## Security Notes

⚠️ **Never commit real credentials to GitHub!**

- Use `.env` files for secrets (already in `.gitignore`)
- Keep production configs separate from git repo
- Use Cloudflare Access or VPN for external access
- Change default passwords immediately

---

## Troubleshooting

**"Connection refused" errors:**
- Check `YOUR_MQTT_BROKER_IP` is correct
- Verify MQTT broker is running: `docker ps`
- Test connection: `telnet YOUR_MQTT_BROKER_IP 1883`

**"Camera links don't work" in Grafana:**
- Update `YOUR_PI_IP` in `beeper_sensors.json`
- Redeploy dashboard: `./deploy_grafana.sh`

**"Cloudflare tunnel not working":**
- Verify `YOUR_DOMAIN` matches your tunnel config
- Check domain in `app.py` line 179

---

## Additional Help

- See `README.md` for project overview
- See `V2_DEPLOYMENT_GUIDE.md` for full deployment steps
- See `V2_PRODUCTION_NOTES.md` for technical details
- Open an issue on GitHub for help

---

**Last Updated:** October 25, 2025
**Version:** 2.0
