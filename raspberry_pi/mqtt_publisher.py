#!/usr/bin/env python3
"""
BEEPER KEEPER 10000 - MQTT Publisher
=====================================

Publishes sensor data from Raspberry Pi to MQTT broker for Grafana visualization.

Publishes:
- BME680 environmental data (temperature, humidity, pressure, gas resistance)
- CPU temperature
- System stats (CPU%, memory%, disk%)
- Camera metadata (if available)

MQTT Topics:
- beeper/sensors/bme680/temperature
- beeper/sensors/bme680/humidity
- beeper/sensors/bme680/pressure
- beeper/sensors/bme680/gas
- beeper/sensors/cpu/temperature
- beeper/system/cpu_percent
- beeper/system/memory_percent
- beeper/system/disk_percent
- beeper/camera/csi/metadata

Dependencies:
- paho-mqtt
- psutil
- adafruit-circuitpython-bme680 (optional)

Install: pip3 install paho-mqtt psutil adafruit-circuitpython-bme680

Author: YOUR_GITHUB_USERNAME
License: MIT
"""

import paho.mqtt.client as mqtt
import time
import json
import psutil
from datetime import datetime
import os
import math

# Load configuration
try:
    from config import *
except ImportError:
    print("WARNING: config.py not found. Using default configuration.")
    MQTT_BROKER = "localhost"
    MQTT_PORT = 1883
    MQTT_CLIENT_ID = "beeper_publisher"
    BME680_ENABLED = True
    BME680_I2C_ADDRESS = 0x76
    PUBLISH_INTERVAL_SECONDS = 10

# Initialize MQTT client
mqtt_client = None
bme680 = None

# BME680 Air Quality Configuration
BME680_BASELINE_FILE = '/tmp/bme680_baseline.json'
bme680_baseline = {
    'gas_baseline': None,
    'hum_baseline': 40.0,
    'calibration_time': None,
    'samples_collected': 0
}

def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the MQTT broker."""
    if rc == 0:
        print(f"✓ Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"✗ Failed to connect to MQTT broker. Return code: {rc}")

def on_publish(client, userdata, mid):
    """Callback for when a message is published."""
    pass  # Uncomment for debugging: print(f"Message {mid} published")

def init_mqtt():
    """Initialize MQTT client connection."""
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_publish = on_publish

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        return True
    except Exception as e:
        print(f"✗ MQTT connection failed: {e}")
        return False

def init_bme680():
    """Initialize BME680 environmental sensor."""
    global bme680
    if not BME680_ENABLED:
        print("ℹ BME680 sensor disabled in configuration")
        return False

    try:
        import board
        import busio
        import adafruit_bme680
        i2c = busio.I2C(board.SCL, board.SDA)

        try:
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=BME680_I2C_ADDRESS)
            print(f"✓ BME680 sensor detected at 0x{BME680_I2C_ADDRESS:02x}")
            # Load baseline calibration
            load_bme680_baseline()
            if bme680_baseline['gas_baseline'] is None:
                print("⚠ BME680: No baseline found. Starting 30-minute calibration...")
            else:
                print(f"✓ BME680: Baseline loaded - Gas: {bme680_baseline['gas_baseline']:.0f}Ω")
            return True
        except:
            # Try alternate address
            alt_address = 0x77 if BME680_I2C_ADDRESS == 0x76 else 0x76
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=alt_address)
            print(f"✓ BME680 sensor detected at 0x{alt_address:02x}")
            return True
    except Exception as e:
        print(f"✗ BME680 initialization failed: {e}")
        return False

def load_bme680_baseline():
    """Load BME680 baseline calibration from file"""
    global bme680_baseline
    try:
        if os.path.exists(BME680_BASELINE_FILE):
            with open(BME680_BASELINE_FILE, 'r') as f:
                saved_baseline = json.load(f)
                bme680_baseline.update(saved_baseline)
                return True
    except Exception as e:
        print(f"⚠ Could not load BME680 baseline: {e}")
    return False

def save_bme680_baseline():
    """Save BME680 baseline calibration to file"""
    try:
        with open(BME680_BASELINE_FILE, 'w') as f:
            json.dump(bme680_baseline, f)
        return True
    except Exception as e:
        print(f"✗ Could not save BME680 baseline: {e}")
    return False

def calculate_gas_resistance_compensated(gas_raw, humidity):
    """Calculate humidity-compensated gas resistance"""
    if gas_raw <= 0:
        return 0
    try:
        log_gas = math.log(gas_raw)
        hum_offset = 0.04 * log_gas * humidity
        comp_gas = log_gas + hum_offset
        return comp_gas
    except:
        return 0

def calculate_iaq(gas_raw, humidity):
    """Calculate Indoor Air Quality (IAQ) index from 0-500"""
    global bme680_baseline

    if bme680_baseline['gas_baseline'] is None:
        if bme680_baseline['samples_collected'] < 180:  # 30 min at 10s intervals
            bme680_baseline['samples_collected'] += 1
            return None
        else:
            bme680_baseline['gas_baseline'] = gas_raw
            bme680_baseline['hum_baseline'] = humidity
            bme680_baseline['calibration_time'] = time.time()
            save_bme680_baseline()
            print(f"✓ BME680: Baseline calibrated! Gas={gas_raw:.0f}Ω, Hum={humidity:.1f}%")
            return 50

    gas_comp = calculate_gas_resistance_compensated(gas_raw, humidity)
    baseline_comp = calculate_gas_resistance_compensated(
        bme680_baseline['gas_baseline'],
        bme680_baseline['hum_baseline']
    )

    if baseline_comp == 0:
        return None

    gas_ratio = baseline_comp / gas_comp if gas_comp > 0 else 1.0
    iaq = 50 + (1.0 - gas_ratio) * 450
    iaq = max(0, min(500, iaq))

    return round(iaq, 1)

def estimate_co2_equivalent(iaq):
    """Estimate CO2 equivalent in ppm from IAQ"""
    if iaq is None:
        return None

    if iaq <= 50:
        co2 = 400 + (iaq / 50) * 200
    elif iaq <= 100:
        co2 = 600 + ((iaq - 50) / 50) * 200
    elif iaq <= 150:
        co2 = 800 + ((iaq - 100) / 50) * 200
    elif iaq <= 200:
        co2 = 1000 + ((iaq - 150) / 50) * 500
    elif iaq <= 300:
        co2 = 1500 + ((iaq - 200) / 100) * 1000
    else:
        co2 = 2500 + ((iaq - 300) / 200) * 2500

    return round(co2, 0)

def get_cpu_temp():
    """Read CPU temperature from thermal zone."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return None

def publish_sensor_data():
    """Read and publish all sensor data to MQTT."""
    timestamp = int(time.time())

    # BME680 Environmental Sensor
    if bme680:
        try:
            # Read raw sensor values
            temperature = round(bme680.temperature, 2)
            humidity = round(bme680.humidity, 2)
            pressure = round(bme680.pressure, 2)
            gas_raw = int(bme680.gas)

            # Calculate air quality metrics
            gas_compensated = calculate_gas_resistance_compensated(gas_raw, humidity)
            iaq = calculate_iaq(gas_raw, humidity)
            co2_equivalent = estimate_co2_equivalent(iaq)

            # Calculate calibration progress
            calibration_progress = 0
            if bme680_baseline['gas_baseline'] is None:
                calibration_progress = round((bme680_baseline['samples_collected'] / 180.0) * 100, 1)

            # Classify IAQ level
            iaq_classification = None
            if iaq is not None:
                if iaq <= 50:
                    iaq_classification = 'Excellent'
                elif iaq <= 100:
                    iaq_classification = 'Good'
                elif iaq <= 150:
                    iaq_classification = 'Moderate'
                elif iaq <= 200:
                    iaq_classification = 'Poor'
                elif iaq <= 300:
                    iaq_classification = 'Very Poor'
                else:
                    iaq_classification = 'Severe'

            data = {
                "temperature": temperature,
                "humidity": humidity,
                "pressure": pressure,
                "gas_raw": gas_raw,
                "gas_compensated": round(gas_compensated, 3) if gas_compensated else None,
                "iaq": iaq,
                "iaq_classification": iaq_classification,
                "co2_equivalent": co2_equivalent,
                "calibration_progress": calibration_progress,
                "timestamp": timestamp,
                "sensor_type": "bme680",
                "location": "raspberry_pi"
            }

            # Publish to individual topics
            mqtt_client.publish("beeper/sensors/bme680/temperature",
                              json.dumps({"value": temperature, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/humidity",
                              json.dumps({"value": humidity, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/pressure",
                              json.dumps({"value": pressure, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/gas",
                              json.dumps({"value": gas_raw, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/gas_compensated",
                              json.dumps({"value": gas_compensated, "timestamp": timestamp}))

            # Publish air quality metrics
            if iaq is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq",
                                  json.dumps({"value": iaq, "timestamp": timestamp}))
            if co2_equivalent is not None:
                mqtt_client.publish("beeper/sensors/bme680/co2_equivalent",
                                  json.dumps({"value": co2_equivalent, "timestamp": timestamp}))
            if iaq_classification is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq_classification",
                                  json.dumps({"value": iaq_classification, "timestamp": timestamp}))

            # Publish combined data
            mqtt_client.publish("beeper/sensors/bme680/all", json.dumps(data))

            # Enhanced logging
            if iaq is not None:
                print(f"📤 BME680: {temperature}°C, {humidity}%, {pressure}hPa, IAQ: {iaq}, CO₂: {co2_equivalent}ppm")
            else:
                print(f"📤 BME680: {temperature}°C, {humidity}%, {pressure}hPa, Gas: {gas_raw}Ω (Calibrating {calibration_progress}%)")
        except Exception as e:
            print(f"✗ BME680 read error: {e}")

    # CPU Temperature
    cpu_temp = get_cpu_temp()
    if cpu_temp:
        data = {
            "cpu_temp": cpu_temp,
            "timestamp": timestamp,
            "sensor_type": "cpu",
            "location": "raspberry_pi"
        }
        mqtt_client.publish("beeper/sensors/cpu/temperature", json.dumps(data))
        print(f"📤 CPU Temp: {cpu_temp}°C")

    # System Stats
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        system_data = {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory.percent, 1),
            "disk_percent": round(disk.percent, 1),
            "timestamp": timestamp
        }

        mqtt_client.publish("beeper/system/stats", json.dumps(system_data))
        mqtt_client.publish("beeper/system/cpu_percent",
                          json.dumps({"value": cpu_percent, "timestamp": timestamp}))
        mqtt_client.publish("beeper/system/memory_percent",
                          json.dumps({"value": memory.percent, "timestamp": timestamp}))
        mqtt_client.publish("beeper/system/disk_percent",
                          json.dumps({"value": disk.percent, "timestamp": timestamp}))

        print(f"📤 System: CPU {cpu_percent}%, RAM {memory.percent}%, Disk {disk.percent}%")
    except Exception as e:
        print(f"✗ System stats error: {e}")

    # Camera Metadata (if available)
    try:
        if os.path.exists('/tmp/camera_metadata.json'):
            with open('/tmp/camera_metadata.json', 'rb') as f:
                f.seek(0, 2)
                file_size = f.tell()
                read_size = min(5000, file_size)
                f.seek(max(0, file_size - read_size))
                tail_data = f.read().decode('utf-8', errors='ignore')

            last_brace = tail_data.rfind('}')
            if last_brace != -1:
                search_start = max(0, last_brace - 2000)
                chunk = tail_data[search_start:last_brace+1]
                first_brace = chunk.rfind('{')
                if first_brace != -1:
                    json_str = chunk[first_brace:]
                    metadata = json.loads(json_str)
                    metadata['timestamp'] = timestamp
                    mqtt_client.publish("beeper/camera/csi/metadata", json.dumps(metadata))
                    print(f"📤 Camera metadata published")
    except Exception as e:
        pass  # Camera metadata is optional

def main():
    """Main loop for MQTT publisher."""
    print("🐔 BEEPER KEEPER 10000 - MQTT Publisher")
    print("=" * 50)

    # Initialize MQTT
    if not init_mqtt():
        print("✗ Failed to initialize MQTT. Exiting.")
        return

    # Initialize BME680
    init_bme680()

    # Wait for MQTT connection
    time.sleep(2)

    print(f"\n📡 Publishing sensor data every {PUBLISH_INTERVAL_SECONDS} seconds")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            publish_sensor_data()
            print()  # Blank line between updates
            time.sleep(PUBLISH_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down MQTT publisher...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("✓ Disconnected from MQTT broker")

if __name__ == "__main__":
    main()
