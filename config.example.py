#!/usr/bin/env python3
"""
BEEPER KEEPER 10000 - Configuration File
Copy this file to config.py and update with your settings
"""

# Network Configuration
RASPBERRY_PI_IP = "192.168.1.100"  # Replace with your Raspberry Pi's IP address
WEBRTC_PORT = 8889                  # MediaMTX WebRTC port
WEB_UI_PORT = 8080                  # Flask web interface port

# Camera Configuration
CSI_CAMERA_STREAM = f"http://{RASPBERRY_PI_IP}:{WEBRTC_PORT}/csi_camera"
USB_CAMERA_STREAM = f"http://{RASPBERRY_PI_IP}:{WEBRTC_PORT}/usb_camera"

# Sensor Configuration (I2C)
BME680_ENABLED = True               # Enable BME680 environmental sensor
BME680_I2C_ADDRESS = 0x76           # I2C address (0x76 or 0x77)

# System Monitoring
UPDATE_INTERVAL_SECONDS = 2         # How often to update sensor data

# MQTT Configuration (for Grafana integration)
MQTT_BROKER = "localhost"            # MQTT broker IP (localhost if running on same Pi)
MQTT_PORT = 1883                     # MQTT broker port
MQTT_CLIENT_ID = "beeper_publisher"  # Unique client ID for MQTT
PUBLISH_INTERVAL_SECONDS = 10        # How often to publish sensor data to MQTT
