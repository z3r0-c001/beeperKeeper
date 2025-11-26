"""
MQTT Service

Handles MQTT client connection and message processing.
"""
import paho.mqtt.client as mqtt
import json
import threading

# Global sensor data storage
sensor_data = {
    'bme680': {},
    'camera': {},
    'system': {},
    'cpu_temperature': 0,
    'audio_level': 0,
    'water': {},
    'food': {},
    'weather': {},
    'last_update': 0
}

sensor_data_lock = threading.Lock()


class MQTTService:
    """MQTT client management"""

    def __init__(self, broker='10.10.10.7', port=1883):
        self.broker = broker
        self.port = port
        self.client = None
        self._connected = False

    def connect(self):
        """Initialize and connect MQTT client"""
        self.client = mqtt.Client(client_id="beeper_webapp")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            return True
        except Exception as e:
            print(f"MQTT connection error: {e}")
            return False

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker}:{self.port}")
            self._connected = True
            # Subscribe to sensor topics
            client.subscribe("beeper/sensors/#")
            client.subscribe("beeper/system/#")
            client.subscribe("beeper/camera/#")
            client.subscribe("beeper/water/#")
            client.subscribe("beeper/audio/#")
            client.subscribe("beeper/feed/#")
            client.subscribe("beeper/lights/#")
            client.subscribe("beeper/weather/#")
        else:
            print(f"MQTT connection failed with code: {rc}")
            self._connected = False

    def _on_message(self, client, userdata, msg):
        """Process incoming MQTT messages"""
        import time
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            with sensor_data_lock:
                # BME680 sensor data
                if topic == "beeper/sensors/bme680/all":
                    sensor_data['bme680'] = payload
                    sensor_data['last_update'] = time.time()

                # CPU temperature
                elif topic == "beeper/sensors/cpu/temperature":
                    sensor_data['cpu_temperature'] = payload.get('cpu_temp', 0)

                # System stats
                elif topic == "beeper/system/stats":
                    sensor_data['system'] = payload

                # Camera metadata
                elif topic == "beeper/camera/csi/metadata":
                    sensor_data['camera'] = payload

                # Audio level
                elif topic == "beeper/audio/level":
                    sensor_data['audio_level'] = payload.get('level_db', 0)

                # Water sensor
                elif topic.startswith("beeper/water/"):
                    if 'water' not in sensor_data:
                        sensor_data['water'] = {}
                    sensor_data['water'].update(payload)

                # Feed level - transform field names for frontend
                elif topic == "beeper/feed/level/all":
                    sensor_data['food'] = {
                        'percentage': payload.get('percent_full', 0),
                        'level': payload.get('level', 'UNKNOWN'),
                        'confidence': payload.get('confidence', 0),
                        'method': payload.get('method', 'unknown')
                    }

                # Weather data
                elif topic == "beeper/weather/all":
                    sensor_data['weather'] = payload

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"MQTT message error: {e}")

    def is_connected(self):
        """Check if MQTT is connected"""
        return self._connected and self.client and self.client.is_connected()

    def publish(self, topic, payload):
        """Publish message to MQTT"""
        if self.client:
            self.client.publish(topic, json.dumps(payload) if isinstance(payload, dict) else payload)

    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# Global MQTT service instance
mqtt_service = MQTTService()
