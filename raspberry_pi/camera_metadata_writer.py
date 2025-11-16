#!/usr/bin/env python3
"""
Simple script to capture Picamera2 metadata and write to /tmp/camera_metadata.json
for mqtt_publisher.py to read and publish to MQTT.
"""
import time
import json
from picamera2 import Picamera2

# Initialize camera
picam2 = Picamera2()
config = picam2.create_still_configuration()
picam2.configure(config)
picam2.start()

print("📷 Camera metadata writer started")

while True:
    try:
        # Capture metadata
        metadata = picam2.capture_metadata()

        # Write to file (mqtt_publisher will read this)
        with open('/tmp/camera_metadata.json', 'w') as f:
            json.dump(metadata, f)

        # Wait before next capture
        time.sleep(2)
    except KeyboardInterrupt:
        print("\n👋 Stopping camera metadata writer")
        break
    except Exception as e:
        print(f"✗ Error: {e}")
        time.sleep(5)

picam2.stop()
