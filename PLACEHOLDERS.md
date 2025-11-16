# PLACEHOLDERS.md

This document lists all placeholder values used in the sanitized GitHub repository. You must replace these with your actual values during deployment.

## Network Configuration

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `10.10.10.7` | Docker host IP address running Grafana stack | `192.168.1.100` or your server IP |
| `10.10.10.28` | Raspberry Pi IP address running sensors/cameras | `192.168.1.101` or your Pi IP |
| `YOUR_DOMAIN` | Your public domain name for web access | `chickens.example.com` |
| `YOUR_WEBSITE` | Your main website domain | `example.com` |

## User Accounts

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `pi_user` | Username on Raspberry Pi | `pi`, `admin`, or your username |
| `dev_user` | Username on development machine | Your local username |
| `user` | Generic user placeholder | Your username |
| `user@example.com` | Email address for alerts | `your-email@gmail.com` |
| `your_github_username` | Your GitHub username | Your actual GitHub username |

## File Paths

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `/home/pi_user/` | Home directory on Raspberry Pi | `/home/pi/` or `/home/yourusername/` |
| `/home/dev_user/` | Home directory on dev machine | `/home/yourname/` |

## How to Replace Placeholders

### Option 1: Manual Find-and-Replace

Use your text editor to find and replace all placeholders with your actual values.

### Option 2: sed Script

Create a script to automate replacements:

```bash
#!/bin/bash
# customize.sh - Replace all placeholders with your values

# YOUR VALUES HERE
DOCKER_HOST_IP="192.168.1.100"
RASPBERRY_PI_IP="192.168.1.101"
YOUR_DOMAIN="chickens.example.com"
YOUR_WEBSITE="example.com"
PI_USERNAME="pi"
DEV_USERNAME="yourname"
YOUR_EMAIL="your-email@gmail.com"
GITHUB_USER="your_github_username"

# Files to update
FILES=$(find . -type f \( -name "*.py" -o -name "*.yml" -o -name "*.yaml" -o -name "*.html" -o -name "*.md" -o -name "*.conf" -o -name "*.service" -o -name "*.sh" \))

for file in $FILES; do
    sed -i "s/10\.10\.10\.7/$DOCKER_HOST_IP/g" "$file"
    sed -i "s/10\.10\.10\.28/$RASPBERRY_PI_IP/g" "$file"
    sed -i "s/YOUR_DOMAIN/$YOUR_DOMAIN/g" "$file"
    sed -i "s/YOUR_WEBSITE/$YOUR_WEBSITE/g" "$file"
    sed -i "s/pi_user/$PI_USERNAME/g" "$file"
    sed -i "s/dev_user/$DEV_USERNAME/g" "$file"
    sed -i "s/user@example\.com/$YOUR_EMAIL/g" "$file"
    sed -i "s/your_github_username/$GITHUB_USER/g" "$file"
    sed -i "s|/home/pi_user/|/home/$PI_USERNAME/|g" "$file"
    sed -i "s|/home/dev_user/|/home/$DEV_USERNAME/|g" "$file"
done

echo "Placeholders replaced successfully!"
```

## Critical Files Requiring Customization

After replacing placeholders, review these files carefully:

1. **docker-compose.yml** - Update all volume paths and network settings
2. **docker/grafana/provisioning/alerting/contactpoints.yaml** - Set your email address
3. **docker/grafana/provisioning/datasources/influxdb.yaml** - Set InfluxDB connection details
4. **docker/telegraf/telegraf.conf** - Set MQTT broker IP and InfluxDB connection
5. **raspberry_pi/config.py** - Set MQTT broker IP and Flask configuration
6. **raspberry_pi/config/mediamtx.yml** - Configure streaming server
7. **raspberry_pi/systemd/*.service** - Update all file paths and usernames
8. **.env.example** - Copy to `.env` and set all secrets (InfluxDB token, Grafana password, etc.)

## Security Notes

- NEVER commit your `.env` file to git (it's in .gitignore)
- Generate strong passwords for InfluxDB and Grafana
- Use a unique InfluxDB API token (do not use the example values)
- Consider using Cloudflare Tunnel or VPN instead of exposing services directly to internet
- Review all email templates to ensure no personal information is embedded

## Sanitization Reference

These were the original → placeholder mappings applied during sanitization:

- Private network IPs replaced with placeholders
- Domain names replaced with YOUR_DOMAIN/YOUR_WEBSITE
- Usernames replaced with generic placeholders
- Email addresses replaced with user@example.com
- GitHub usernames replaced with your_github_username
- All home directory paths updated to match username placeholders

**After customization, this PLACEHOLDERS.md file should be deleted from your production deployment.**
