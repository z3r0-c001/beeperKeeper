#!/usr/bin/env python3
"""
BEEPER KEEPER - Shared Utilities Module
========================================

Common functions shared across BeeperKeeper components:
- Configuration loading with environment variable fallbacks
- MQTT connection handling
- Sensor data formatting
- System metrics collection

Author: your_github_username
License: MIT
"""

import os
import json
import psutil
from datetime import datetime
import paho.mqtt.client as mqtt


# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

def load_config():
    """
    Load configuration from config.py with environment variable fallbacks.

    Returns:
        dict: Configuration dictionary with keys:
            - MQTT_BROKER: MQTT broker hostname/IP
            - MQTT_PORT: MQTT broker port
            - MQTT_CLIENT_ID: MQTT client identifier
            - BME680_ENABLED: Whether BME680 sensor is enabled
            - BME680_I2C_ADDRESS: I2C address of BME680 sensor
            - PUBLISH_INTERVAL_SECONDS: How often to publish sensor data
    """
    config = {}

    # Try to load from config.py first
    try:
        import config as cfg
        config['MQTT_BROKER'] = getattr(cfg, 'MQTT_BROKER', None)
        config['MQTT_PORT'] = getattr(cfg, 'MQTT_PORT', None)
        config['MQTT_CLIENT_ID'] = getattr(cfg, 'MQTT_CLIENT_ID', None)
        config['BME680_ENABLED'] = getattr(cfg, 'BME680_ENABLED', True)
        config['BME680_I2C_ADDRESS'] = getattr(cfg, 'BME680_I2C_ADDRESS', 0x76)
        config['PUBLISH_INTERVAL_SECONDS'] = getattr(cfg, 'PUBLISH_INTERVAL_SECONDS', 10)
    except ImportError:
        pass

    # Apply environment variable fallbacks
    config['MQTT_BROKER'] = config.get('MQTT_BROKER') or os.environ.get('MQTT_BROKER_HOST', 'localhost')
    config['MQTT_PORT'] = config.get('MQTT_PORT') or int(os.environ.get('MQTT_BROKER_PORT', 1883))
    config['MQTT_CLIENT_ID'] = config.get('MQTT_CLIENT_ID') or os.environ.get('MQTT_CLIENT_ID', 'beeper_default')
    config['BME680_ENABLED'] = config.get('BME680_ENABLED', True)
    config['BME680_I2C_ADDRESS'] = config.get('BME680_I2C_ADDRESS', 0x76)
    config['PUBLISH_INTERVAL_SECONDS'] = config.get('PUBLISH_INTERVAL_SECONDS', 10)

    return config


# ============================================================================
# MQTT CONNECTION HELPERS
# ============================================================================

def connect_mqtt_with_retry(broker_host, broker_port, client_id, max_retries=5):
    """
    Connect to MQTT broker with exponential backoff retry logic.

    Args:
        broker_host (str): MQTT broker hostname or IP
        broker_port (int): MQTT broker port
        client_id (str): MQTT client identifier
        max_retries (int): Maximum number of connection attempts (default: 5)

    Returns:
        bool: True if connected successfully, False otherwise
    """
    for attempt in range(1, max_retries + 1):
        try:
            client = mqtt.Client(client_id=client_id)
            client.connect(broker_host, broker_port, 60)
            print(f"✓ Connected to MQTT broker at {broker_host}:{broker_port}")
            return client
        except Exception as e:
            delay = min(2 ** attempt, 30)  # Exponential backoff, max 30s
            print(f"✗ MQTT connection attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                print(f"  Retrying in {delay} seconds...")
                import time
                time.sleep(delay)
            else:
                print("✗ Failed to connect to MQTT broker after maximum retries")
                return None


# ============================================================================
# SENSOR DATA FORMATTING
# ============================================================================

def format_sensor_message(sensor_type, data, timestamp=None):
    """
    Format sensor data into standard MQTT message structure.

    Args:
        sensor_type (str): Type of sensor (e.g., 'bme680', 'cpu', 'audio')
        data (dict): Sensor reading data
        timestamp (float, optional): Unix timestamp. Defaults to current time.

    Returns:
        str: JSON-formatted message string
    """
    if timestamp is None:
        timestamp = datetime.now().timestamp()

    message = {
        'sensor_type': sensor_type,
        'timestamp': timestamp,
        'data': data
    }

    return json.dumps(message)


def format_bme680_message(temperature, humidity, pressure, gas_resistance, iaq=None, co2_equivalent=None):
    """
    Format BME680 sensor data into standard message structure.

    Args:
        temperature (float): Temperature in Celsius
        humidity (float): Relative humidity in percent
        pressure (float): Atmospheric pressure in hPa
        gas_resistance (float): Gas resistance in Ohms
        iaq (int, optional): Indoor Air Quality index (0-500)
        co2_equivalent (int, optional): Estimated CO2 in ppm

    Returns:
        dict: Formatted BME680 data
    """
    data = {
        'temperature': round(temperature, 2),
        'humidity': round(humidity, 2),
        'pressure': round(pressure, 2),
        'gas_resistance': round(gas_resistance, 2)
    }

    if iaq is not None:
        data['iaq'] = int(iaq)
        data['air_quality'] = get_air_quality_description(iaq)

    if co2_equivalent is not None:
        data['co2_equivalent'] = int(co2_equivalent)

    return data


def get_air_quality_description(iaq):
    """
    Convert IAQ index to human-readable description.

    Args:
        iaq (int): Indoor Air Quality index (0-500)

    Returns:
        str: Air quality description
    """
    if iaq <= 50:
        return "Excellent"
    elif iaq <= 100:
        return "Good"
    elif iaq <= 150:
        return "Lightly Polluted"
    elif iaq <= 200:
        return "Moderately Polluted"
    elif iaq <= 250:
        return "Heavily Polluted"
    elif iaq <= 350:
        return "Severely Polluted"
    else:
        return "Extremely Polluted"


# ============================================================================
# SYSTEM METRICS
# ============================================================================

def get_cpu_temperature():
    """
    Get CPU temperature from Raspberry Pi thermal sensor.

    Returns:
        float: CPU temperature in Celsius, or None if unavailable
    """
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = float(f.read().strip()) / 1000.0
            return round(temp, 2)
    except Exception as e:
        print(f"Warning: Could not read CPU temperature: {e}")
        return None


def get_system_stats():
    """
    Get system resource usage statistics.

    Returns:
        dict: System statistics with keys:
            - cpu_percent: CPU usage percentage
            - memory_percent: Memory usage percentage
            - disk_percent: Disk usage percentage
            - uptime_seconds: System uptime in seconds
    """
    try:
        stats = {
            'cpu_percent': round(psutil.cpu_percent(interval=1), 2),
            'memory_percent': round(psutil.virtual_memory().percent, 2),
            'disk_percent': round(psutil.disk_usage('/').percent, 2),
            'uptime_seconds': int(datetime.now().timestamp() - psutil.boot_time())
        }
        return stats
    except Exception as e:
        print(f"Warning: Could not read system stats: {e}")
        return {}


def get_network_stats():
    """
    Get network interface statistics.

    Returns:
        dict: Network statistics with keys:
            - bytes_sent: Total bytes sent
            - bytes_recv: Total bytes received
            - packets_sent: Total packets sent
            - packets_recv: Total packets received
    """
    try:
        net = psutil.net_io_counters()
        return {
            'bytes_sent': net.bytes_sent,
            'bytes_recv': net.bytes_recv,
            'packets_sent': net.packets_sent,
            'packets_recv': net.packets_recv
        }
    except Exception as e:
        print(f"Warning: Could not read network stats: {e}")
        return {}


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def validate_sensor_reading(value, min_val=None, max_val=None):
    """
    Validate that a sensor reading is within acceptable bounds.

    Args:
        value: Sensor reading value
        min_val: Minimum acceptable value (optional)
        max_val: Maximum acceptable value (optional)

    Returns:
        bool: True if value is valid, False otherwise
    """
    if value is None:
        return False

    try:
        value = float(value)
    except (TypeError, ValueError):
        return False

    if min_val is not None and value < min_val:
        return False

    if max_val is not None and value > max_val:
        return False

    return True


# ============================================================================
# MODULE INFO
# ============================================================================

__version__ = "1.0.0"
__all__ = [
    'load_config',
    'connect_mqtt_with_retry',
    'format_sensor_message',
    'format_bme680_message',
    'get_air_quality_description',
    'get_cpu_temperature',
    'get_system_stats',
    'get_network_stats',
    'validate_sensor_reading'
]


if __name__ == "__main__":
    # Test configuration loading
    print("Testing beeper_utils module:")
    print("\n1. Configuration loading:")
    config = load_config()
    for key, value in config.items():
        print(f"   {key}: {value}")

    print("\n2. System metrics:")
    print(f"   CPU temperature: {get_cpu_temperature()}°C")
    stats = get_system_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n3. BME680 data formatting:")
    bme_data = format_bme680_message(22.5, 45.2, 1013.25, 150000, iaq=75, co2_equivalent=950)
    print(f"   {json.dumps(bme_data, indent=2)}")

    print("\n✓ All tests completed")
