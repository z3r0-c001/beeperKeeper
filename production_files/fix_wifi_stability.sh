#!/bin/bash
# WiFi Stability Fix for Raspberry Pi 3B+
# Disables power management and optimizes WiFi settings

set -e

echo "================================================"
echo "WiFi Stability Fix for motionOne"
echo "================================================"

# 1. Check current WiFi status
echo -e "\n[1/5] Checking current WiFi status..."
echo "Interface: wlan0"
iw dev wlan0 info || echo "Warning: Could not get WiFi info"

# Check signal
echo -e "\nCurrent signal strength:"
iw dev wlan0 link | grep signal || echo "Not connected"

# Check power save status
echo -e "\nCurrent power save status:"
iw dev wlan0 get power_save || echo "Could not check power save"

# 2. Disable WiFi power management (immediate)
echo -e "\n[2/5] Disabling WiFi power management (immediate)..."
sudo iw dev wlan0 set power_save off
echo "Power save disabled for current session"

# 3. Make power management change persistent
echo -e "\n[3/5] Making WiFi power management change persistent..."

# Create systemd service to disable power save on boot
sudo tee /etc/systemd/system/wifi-powersave-off.service > /dev/null << 'SERVICE_EOF'
[Unit]
Description=Disable WiFi Power Management
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/iw dev wlan0 set power_save off
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo systemctl daemon-reload
sudo systemctl enable wifi-powersave-off.service
echo "✓ Power save will be disabled on every boot"

# 4. Optimize WiFi settings in /etc/sysctl.conf
echo -e "\n[4/5] Optimizing network settings..."

# Backup sysctl.conf
sudo cp /etc/sysctl.conf /etc/sysctl.conf.backup

# Add WiFi optimizations if not already present
if ! grep -q "# WiFi Stability Optimizations" /etc/sysctl.conf; then
    sudo tee -a /etc/sysctl.conf > /dev/null << 'SYSCTL_EOF'

# WiFi Stability Optimizations (added by motionOne setup)
# Disable IPv6 to reduce network overhead
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1

# TCP keepalive settings for better connection detection
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6
SYSCTL_EOF
    
    sudo sysctl -p
    echo "✓ Network settings optimized"
else
    echo "✓ Network settings already optimized"
fi

# 5. Add WiFi reconnect script
echo -e "\n[5/5] Installing WiFi watchdog..."

sudo tee /usr/local/bin/wifi_watchdog.sh > /dev/null << 'WATCHDOG_EOF'
#!/bin/bash
# WiFi Watchdog - Monitors and fixes WiFi connection
# Pings router, if fails 3 times, restarts WiFi

ROUTER_IP="172.16.0.1"  # Change if your router IP is different
PING_COUNT=3
PING_TIMEOUT=5

# Try to ping router
if ! ping -c $PING_COUNT -W $PING_TIMEOUT $ROUTER_IP &> /dev/null; then
    echo "$(date): WiFi connection lost, attempting recovery..." | tee -a /var/log/wifi_watchdog.log
    
    # Restart WiFi interface
    sudo ip link set wlan0 down
    sleep 2
    sudo ip link set wlan0 up
    sleep 5
    
    # Disable power save again
    sudo iw dev wlan0 set power_save off
    
    echo "$(date): WiFi recovery attempted" | tee -a /var/log/wifi_watchdog.log
fi
WATCHDOG_EOF

sudo chmod +x /usr/local/bin/wifi_watchdog.sh

# Create cron job for WiFi watchdog (every 2 minutes)
(crontab -l 2>/dev/null | grep -v wifi_watchdog; echo "*/2 * * * * /usr/local/bin/wifi_watchdog.sh") | crontab -
echo "✓ WiFi watchdog installed (checks every 2 minutes)"

# Final status check
echo -e "\n================================================"
echo "WiFi Stability Fix Applied Successfully!"
echo "================================================"
echo -e "\nCurrent Status:"
iw dev wlan0 get power_save
iw dev wlan0 link | grep signal || echo "Signal: Not available"

echo -e "\nChanges made:"
echo "✓ WiFi power save disabled (immediate)"
echo "✓ Power save disabled on boot (systemd service)"
echo "✓ Network settings optimized"
echo "✓ WiFi watchdog installed (auto-reconnect every 2 min)"

echo -e "\nRecommendations:"
echo "1. Reboot to apply all changes: sudo reboot"
echo "2. Monitor logs: tail -f /var/log/wifi_watchdog.log"
echo "3. Check status: iw dev wlan0 get power_save"

echo -e "\n================================================"
