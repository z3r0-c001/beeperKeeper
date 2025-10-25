#!/bin/bash
# WiFi Diagnostics Script for motionOne

echo "=========================================="
echo "WiFi Diagnostics Report"
echo "Time: $(date)"
echo "=========================================="

echo -e "\n[1] WiFi Interface Info:"
iw dev wlan0 info 2>/dev/null || echo "ERROR: Could not get interface info"

echo -e "\n[2] Current Connection:"
iw dev wlan0 link 2>/dev/null || echo "ERROR: Not connected"

echo -e "\n[3] Power Save Status:"
iw dev wlan0 get power_save 2>/dev/null || echo "ERROR: Could not check"

echo -e "\n[4] Signal Quality:"
cat /proc/net/wireless 2>/dev/null || echo "ERROR: Could not read wireless stats"

echo -e "\n[5] Recent WiFi Kernel Messages:"
sudo dmesg | grep -i 'brcmfmac\|wlan\|wifi\|80211' | tail -20

echo -e "\n[6] Network Interface Status:"
ip addr show wlan0

echo -e "\n[7] Routing Table:"
ip route

echo -e "\n[8] Ping Test to Router:"
ping -c 5 -W 2 172.16.0.1 2>&1 || echo "ERROR: Cannot reach router"

echo -e "\n[9] DNS Resolution Test:"
ping -c 2 -W 2 8.8.8.8 2>&1 || echo "ERROR: Cannot reach internet"

echo -e "\n=========================================="
echo "End of Diagnostics"
echo "=========================================="
