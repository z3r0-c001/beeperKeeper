#!/usr/bin/env python3
"""
Publish lights-out warning message to MQTT.
Meant to be called by cron at 6:45 PM daily.
"""
import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
import pytz

# Configuration
MQTT_BROKER = "10.10.10.7"
MQTT_PORT = 1883
CLIENT_ID = "lights_warning_publisher"

def publish_warning():
    """Publish 15-minute warning before lights out."""
    try:
        # Connect to MQTT
        client = mqtt.Client(client_id=CLIENT_ID)
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        # Create warning message
        est = pytz.timezone('America/New_York')
        now = datetime.now(est)
        timestamp = int(time.time())
        
        warning_data = {
            "event": "lights_out_warning",
            "minutes_remaining": 15,
            "lights_out_time": "19:00",
            "timestamp": timestamp,
            "local_time": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "message": "Lights will turn off in 15 minutes",
            "sensor_type": "schedule",
            "location": "raspberry_pi"
        }
        
        # Publish to MQTT
        client.publish("beeper/lights/warning", json.dumps(warning_data))
        
        # Disconnect
        client.disconnect()
        
        print(f"✓ Published lights-out warning at {now.strftime('%H:%M:%S')}")
        return True
        
    except Exception as e:
        print(f"✗ Error publishing warning: {e}")
        return False

if __name__ == "__main__":
    publish_warning()
