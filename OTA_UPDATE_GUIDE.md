# ESP32 Water Sensor - OTA Update Guide

## Overview
The water sensor now supports Over-The-Air (OTA) firmware updates, allowing you to push new code without physically accessing the ESP32.

---

## OTA Configuration

**Hostname:** `ESP32-WaterLevel`
**IP Address:** `YOUR_ESP32_IP` (check Serial Monitor for current IP)
**Port:** `3232` (default)
**Password:** `YOUR_OTA_PASSWORD` (⚠️ Change this in production!)

---

## How to Update Firmware via OTA

### Method 1: Arduino IDE (Easiest)

1. **Open Arduino IDE** with your updated code
2. **Select OTA Port:**
   - Tools → Port → Select "ESP32-WaterLevel at YOUR_ESP32_IP"
   - If you don't see it, wait 30 seconds and refresh (ESP32 needs to be running)
3. **Upload:**
   - Click Upload button as normal
   - Arduino IDE will compile and upload via WiFi
   - ESP32 will reboot automatically with new firmware

**Expected Output:**
```
Uploading over network to ESP32-WaterLevel at YOUR_ESP32_IP...
Progress: [====================] 100%
Upload complete! Rebooting...
```

### Method 2: PlatformIO (Advanced)

In `platformio.ini`:
```ini
upload_protocol = espota
upload_port = YOUR_ESP32_IP
upload_flags =
  --auth=YOUR_OTA_PASSWORD
  --port=3232
```

Then: `pio run -t upload`

### Method 3: Python Script (Command Line)

```bash
python ~/.arduino15/packages/esp32/hardware/esp32/*/tools/espota.py \
  -i YOUR_ESP32_IP \
  -p 3232 \
  -a YOUR_OTA_PASSWORD \
  -f /path/to/firmware.bin
```

---

## Changes in This Update

### 1. OTA Support Added
- ✅ Remote firmware updates
- ✅ Progress monitoring
- ✅ Password protection
- ✅ Error handling

### 2. Timestamp Issue Fixed
- ❌ **OLD:** Sent `"timestamp": 630` (device uptime in seconds)
- ✅ **NEW:** No timestamp field (Telegraf uses current server time)
- **Impact:** Data will now appear with correct 2025 timestamps in InfluxDB/Grafana

### 3. Library Requirements
- **NEW:** `ArduinoOTA` library (built-in to ESP32 core, no install needed)

---

## Verification After OTA Update

### Check Serial Monitor
```
✓ WiFi connected
  IP address: YOUR_ESP32_IP
✓ OTA updates enabled
  Hostname: ESP32-WaterLevel | IP: YOUR_ESP32_IP
```

### Check MQTT Messages
```bash
ssh YOUR_PI_USERNAME@YOUR_MONITORING_SERVER_IP "docker exec YOUR_CONTAINER_PREFIX_mosquitto mosquitto_sub -h localhost -t 'beeper/water/#' -v"
```

**Expected (no timestamp field):**
```json
beeper/water/tank {
  "distance_cm": 201.1,
  "water_level_cm": 0,
  "percent_full": 0,
  "tank_height_cm": 27.94,
  "sensor_type": "water_level",
  "location": "coop_main",
  "rssi": -45,
  "heap_free": 232616,
  "uptime_s": 630
}
```

### Check Grafana Dashboard
- Open http://YOUR_MONITORING_SERVER_IP:3000
- Navigate to "Beeper Test Board - Complete"
- Scroll to bottom
- **Water panels should now show data!**

---

## Troubleshooting OTA

### ESP32 Not Appearing in Arduino IDE Port List

**Causes:**
- ESP32 not on same network as your computer
- mDNS not working on your network
- Firewall blocking port 3232

**Fixes:**
1. **Use IP address directly:**
   - Tools → Port → Add Custom → `YOUR_ESP32_IP`
2. **Check ESP32 is running:**
   - Serial Monitor should show "OTA updates enabled"
3. **Ping test:**
   ```bash
   ping YOUR_ESP32_IP
   ```

### OTA Upload Fails with "Auth Failed"

**Cause:** Wrong password

**Fix:** Verify password is `YOUR_OTA_PASSWORD` (or whatever you changed it to)

### OTA Upload Fails with "Connect Failed"

**Causes:**
- ESP32 crashed or rebooted
- WiFi disconnected
- Network routing issue

**Fix:**
1. Check Serial Monitor - is ESP32 still running?
2. Verify IP address hasn't changed (DHCP reservation recommended)
3. Power cycle ESP32 and try again

### OTA Upload Hangs at "Uploading..."

**Cause:** Network timeout or congestion

**Fix:**
- Wait 2 minutes (large firmware can take time)
- If still stuck, press reset on ESP32 and retry
- Check WiFi signal strength (Serial Monitor shows RSSI)

---

## Security Considerations

### Current Security
- ✅ Password protected (`YOUR_OTA_PASSWORD`)
- ⚠️ Password hardcoded in firmware (visible to anyone with binary)
- ⚠️ No encryption (OTA over plain WiFi)

### Recommendations

1. **Change Default Password:**
   ```cpp
   ArduinoOTA.setPassword("YOUR_STRONG_PASSWORD_HERE");
   ```

2. **Add MAC Address Filtering** (router-level)

3. **Use Separate IoT VLAN** (already done - 192.168.4.x network)

4. **Disable OTA in Production** (optional):
   ```cpp
   // Comment out in setup():
   // setupOTA();

   // Comment out in loop():
   // ArduinoOTA.handle();
   ```

---

## OTA Update Best Practices

### Before Pushing Update
- ✅ Test code on bench first
- ✅ Verify Serial Monitor output
- ✅ Check MQTT messages manually
- ✅ Keep backup of working firmware

### During Update
- ⏱️ Don't power off ESP32 during OTA
- ⏱️ Wait for "Upload complete" message
- ⏱️ Allow ESP32 to reboot (10 seconds)

### After Update
- ✅ Check Serial Monitor for clean boot
- ✅ Verify measurements publishing
- ✅ Check Grafana dashboard
- ✅ Monitor for 24 hours

---

## Rollback Procedure

If OTA update causes issues:

### Option 1: Re-flash via USB
1. Connect ESP32 via USB cable
2. Flash previous working firmware
3. Diagnose issue offline

### Option 2: OTA Rollback
1. Keep backup `.bin` file of working firmware
2. Use OTA to flash backup firmware
3. ESP32 returns to working state

**To create backup firmware:**
- Arduino IDE: Sketch → Export Compiled Binary
- Binary saved to sketch folder as `sensor.ino.esp32.bin`

---

## Production Deployment Record

**Date:** October 30, 2025
**Status:** ✅ **SUCCESSFULLY DEPLOYED**

### OTA Update via Arduino IDE
1. **Selected Port:** ESP32-WaterLevel at YOUR_ESP32_IP
2. **Upload Time:** ~45 seconds over WiFi
3. **Result:** ESP32 rebooted successfully with new firmware

### Post-Deployment Verification
```
Serial Monitor Output:
✓ WiFi connected
  IP address: YOUR_ESP32_IP
✓ OTA updates enabled
  Hostname: ESP32-WaterLevel | IP: YOUR_ESP32_IP
WARNING: NTP time sync failed after 30 seconds
Setup complete. Starting measurements...
📏 Distance: 8.0 cm | 💧 Level: 20.0 cm | 📊 Tank: 71.5%
✓ MQTT published
```

### Grafana Dashboard Status
- **Panel 602 (Water Level Bar Gauge):** ✅ Displaying 71.5%
- **Panel 603 (Water Level cm):** ✅ Displaying 20.0 cm
- **Panel 604 (Water Sensor Status):** ✅ Displaying "✅ Online"
- **Panel 605 (Water Level Timeline):** ✅ 24h graph with data

### Known Issues (Non-Blocking)
- **NTP Sync Failure:** ESP32 cannot reach external NTP servers (network routing)
  - **Impact:** None - Telegraf uses server time for all timestamps
  - **Workaround:** Using millis() fallback successfully

---

## Summary

**OTA Enabled:** ✅
**Timestamp Fixed:** ✅
**Deployment Status:** ✅ **COMPLETE**
**System Status:** 🟢 **FULLY OPERATIONAL**

Water sensor is now integrated with BeeperKeeper system and publishing data every 30 seconds to Grafana dashboard!
