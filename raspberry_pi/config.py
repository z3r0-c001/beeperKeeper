# BEEPER KEEPER 10000 - MQTT Publisher Configuration

# MQTT Broker Settings
MQTT_BROKER = "YOUR_MQTT_BROKER_IP"  # Telegraf/InfluxDB/Grafana server
MQTT_PORT = 1883
MQTT_CLIENT_ID = "beeper_publisher_v2"

# Sensor Settings
BME680_ENABLED = True
BME680_I2C_ADDRESS = 0x76

# Publishing interval (seconds)
PUBLISH_INTERVAL_SECONDS = 10

# Camera Monitor Settings (for camera_monitor.py)
RASPBERRY_PI_IP = 'YOUR_PI_IP'
WEBRTC_PORT = 8889
WEB_UI_PORT = 8080
UPDATE_INTERVAL_SECONDS = 2
