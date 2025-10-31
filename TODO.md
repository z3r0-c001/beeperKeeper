# BeeperKeeper - TODO List

**Last Updated:** October 30, 2025

---

## 🔴 High Priority (Tomorrow)

### Add Photo Resistor to Water Sensor
**Issue:** Need reliable light detection for chicken coop
**Hardware:** Add photoresistor (light-dependent resistor) to ESP32 water sensor
**Why:** Camera Lux sensor unreliable (frozen at 204), need accurate light detection
**Details:**
- Use simple photoresistor connected to ESP32 ADC pin (GPIO 34 or 35)
- Voltage divider circuit: 10kΩ resistor + photoresistor
- Read analog value, map to light ON/OFF threshold
- Publish to MQTT topic: `beeper/lights/photoresistor`
- More reliable than camera metadata for light schedule verification

**Hardware needed:**
- Photoresistor (CdS cell) - $0.50
- 10kΩ resistor - $0.10
- Jumper wires

**Code changes:**
- Add ADC reading function in `sensor.ino`
- Calibrate threshold for coop lighting
- Publish alongside water level data

### Fix OTA Updater
**Issue:** OTA firmware update functionality needs attention
**Context:** ESP32 water sensor has OTA capability enabled, but may need optimization or troubleshooting
**Details:**
- Current OTA configuration: ESP32-WaterLevel at YOUR_ESP32_IP, port 3232
- Password: YOUR_OTA_PASSWORD (should be changed for security)
- Review OTA stability and error handling
- Consider adding automatic retry logic for failed updates

**Files to review:**
- `/opt/beeperKeeper/waterSensor/sensor.ino` - OTA setup code (lines 214-256)
- `OTA_UPDATE_GUIDE.md` - Documentation for OTA procedures

**Possible improvements:**
1. Add OTA progress callback for better monitoring
2. Implement version tracking to prevent downgrade
3. Add pre-update validation (heap check, WiFi signal strength)
4. Test OTA with larger firmware binaries
5. Document rollback procedure in case of failed update

---

## 🟡 Medium Priority

### Optimize Camera Metadata System
**Issue:** CSI camera Lux readings frozen/unreliable due to metadata file size limit
**Context:** Removed Lux-based light detection in favor of time-based detection
**Status:** Panel 204 now uses time-based detection (6:30 AM - 7 PM schedule)
**Follow-up:** Consider removing metadata_updater.py entirely or fixing 1MB file rotation

### Review Alert Rules
**Status:** Removed "Sensor Data Stale" and "InfluxDB Write Rate Low" alerts (too noisy)
**Follow-up:** Review remaining alert thresholds for accuracy

---

## 🟢 Low Priority

### Seasonal Schedule Adjustment
**Context:** Light schedule currently hardcoded to 6:30 AM - 7:00 PM
**Future task:** Adjust schedule for seasonal daylight changes
**Next review:** Spring 2026 (consider 6:00 AM - 8:00 PM for summer)

### Hardware Light Sensor Option
**Idea:** Add dedicated light sensor (TSL2591, BH1750) if camera Lux unreliable long-term
**Benefit:** More accurate light detection without relying on camera metadata
**Cost:** ~$10 for sensor, minimal code changes

### WiFi Credential Security
**Issue:** ESP32 has hardcoded WiFi credentials in firmware
**Solution:** Implement WiFiManager library for web-based credential entry
**Benefit:** More secure, easier to update credentials without reflashing

---

## ✅ Completed (October 30, 2025)

- ✅ Water sensor integration with MQTT/Telegraf/InfluxDB/Grafana
- ✅ Panel 204 converted to time-based light detection
- ✅ Added "Water Management Status" row to dashboard
- ✅ Removed noisy alert rules (Sensor Data Stale, InfluxDB Write Rate Low)
- ✅ OTA update capability added to ESP32 water sensor
- ✅ Comprehensive documentation (OTA guide, session summaries)
- ✅ All files sanitized and pushed to GitHub

---

## 📝 Notes

- Water sensor readings: 71.5% full as of 8 PM Oct 30
- Panel 601 (Chicken Activity): Working correctly
- Panel 604 (Water Sensor Status): Showing "Online" correctly
- All Grafana panels operational with correct data flow

**Next Session Focus:** OTA updater improvements and testing
