#!/usr/bin/env python3
"""
BEEPER KEEPER v2.0 - Streamlined Camera Monitoring System
==========================================================

HLS-based dual camera streaming with BME680 sensor integration
and real-time metrics via MQTT.

Author: YOUR_GITHUB_USERNAME
"""

from flask import Flask, render_template, jsonify, Response, request
import paho.mqtt.client as mqtt
import json
import time
import psutil
import threading
import requests
from datetime import datetime

app = Flask(__name__)

# Configuration
MQTT_BROKER = "YOUR_MQTT_BROKER_IP"
MQTT_PORT = 1883
MEDIAMTX_HLS_PORT = 8888

# Global sensor data storage
sensor_data = {
    'bme680': {},
    'camera': {},
    'system': {},
    'cpu_temperature': 0,
    'last_update': 0
}

# MQTT Client
mqtt_client = None

def on_mqtt_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        print(f"✓ Connected to MQTT broker at {MQTT_BROKER}")
        # Subscribe to all sensor topics
        client.subscribe([
            ("beeper/sensors/bme680/#", 0),
            ("beeper/sensors/cpu/#", 0),
            ("beeper/system/#", 0),
            ("beeper/camera/csi/metadata", 0)
        ])
    else:
        print(f"✗ MQTT connection failed: {rc}")

def on_mqtt_message(client, userdata, msg):
    """MQTT message callback"""
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic

        # Route messages to appropriate storage
        if 'bme680' in topic:
            if topic.endswith('/all'):
                sensor_data['bme680'] = payload
        elif 'cpu/temperature' in topic:
            sensor_data['cpu_temperature'] = payload.get('cpu_temp', 0)
        elif 'system/stats' in topic:
            sensor_data['system'] = payload
        elif 'camera/csi/metadata' in topic:
            sensor_data['camera'] = payload

        sensor_data['last_update'] = time.time()
    except Exception as e:
        print(f"MQTT message error: {e}")

def init_mqtt():
    """Initialize MQTT connection"""
    global mqtt_client
    mqtt_client = mqtt.Client(client_id="beeper_v2_web")
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        return True
    except Exception as e:
        print(f"✗ MQTT initialization failed: {e}")
        return False

def get_cpu_temp():
    """Read CPU temperature"""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return sensor_data.get('cpu_temperature', 0)

def get_system_stats():
    """Get system statistics"""
    try:
        cpu_percent = round(psutil.cpu_percent(interval=0.5), 1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            'cpu_percent': cpu_percent,
            'memory_percent': round(memory.percent, 1),
            'disk_percent': round(disk.percent, 1),
            'uptime_seconds': int(time.time() - psutil.boot_time())
        }
    except:
        return sensor_data.get('system', {})

def format_bme680_data(data):
    """Format BME680 sensor data for display"""
    if not data:
        return {}

    # Check if IAQ is available (calibration complete)
    calibrating = data.get('iaq') is None

    # Get calibration progress from data or calculate estimate
    calibration_progress = data.get('calibration_progress', 0)

    if calibrating:
        # Show calibrating status with progress
        return {
            'temperature': round(data.get('temperature', 0), 1),
            'humidity': round(data.get('humidity', 0), 1),
            'pressure': round(data.get('pressure', 0), 1),
            'gas_raw': int(data.get('gas_raw', 0)),
            'calibration_status': 'calibrating',
            'calibration_progress': calibration_progress
        }

    # Classify IAQ level
    iaq = data.get('iaq', 0)
    if iaq <= 50:
        iaq_class = 'Excellent'
    elif iaq <= 100:
        iaq_class = 'Good'
    elif iaq <= 150:
        iaq_class = 'Moderate'
    elif iaq <= 200:
        iaq_class = 'Poor'
    elif iaq <= 300:
        iaq_class = 'Very Poor'
    else:
        iaq_class = 'Severe'

    return {
        'temperature': round(data.get('temperature', 0), 1),
        'humidity': round(data.get('humidity', 0), 1),
        'pressure': round(data.get('pressure', 0), 1),
        'gas_raw': int(data.get('gas_raw', 0)),
        'iaq': round(data.get('iaq', 0), 1) if data.get('iaq') else None,
        'iaq_classification': iaq_class,
        'co2_equivalent': int(data.get('co2_equivalent', 0)) if data.get('co2_equivalent') else None,
        'calibration_status': 'ready'
    }

def format_camera_metadata(data):
    """Format camera metadata for display"""
    if not data:
        return {}

    return {
        'exposure_time': int(data.get('ExposureTime', 0)),
        'analogue_gain': round(data.get('AnalogueGain', 0), 2),
        'lux': round(data.get('Lux', 0), 1) if data.get('Lux') else None,
        'colour_temp': int(data.get('ColourTemperature', 0)) if data.get('ColourTemperature') else None
    }

def get_base_url():
    """Dynamically determine base URL based on request"""
    # If accessing via Cloudflare domain or localhost, use relative URLs
    host = request.host.lower()
    if 'YOUR_BASE_DOMAIN' in host or 'localhost' in host or '127.0.0.1' in host:
        # Return empty string to use relative URLs (which stay within Cloudflare tunnel)
        return ''
    else:
        # Direct local network access
        return f'http://{request.host.split(":")[0]}:{MEDIAMTX_HLS_PORT}'

@app.route('/')
def index():
    """Main page"""
    base_url = get_base_url()
    return render_template('index.html', hls_base=base_url)

# HLS Proxy Routes (for Cloudflare tunnel compatibility)
@app.route('/csi_camera/<path:subpath>')
def proxy_csi_camera(subpath):
    """Proxy CSI camera HLS stream"""
    try:
        url = f'http://localhost:{MEDIAMTX_HLS_PORT}/csi_camera/{subpath}'
        resp = requests.get(url, stream=True, timeout=10)

        # Determine content type
        content_type = resp.headers.get('Content-Type', 'application/vnd.apple.mpegurl')

        return Response(resp.iter_content(chunk_size=8192),
                       content_type=content_type,
                       headers={'Access-Control-Allow-Origin': '*'})
    except Exception as e:
        return Response(f"Error proxying CSI camera: {e}", status=502)

@app.route('/usb_camera/<path:subpath>')
def proxy_usb_camera(subpath):
    """Proxy USB camera HLS stream"""
    try:
        url = f'http://localhost:{MEDIAMTX_HLS_PORT}/usb_camera/{subpath}'
        resp = requests.get(url, stream=True, timeout=10)

        # Determine content type
        content_type = resp.headers.get('Content-Type', 'application/vnd.apple.mpegurl')

        return Response(resp.iter_content(chunk_size=8192),
                       content_type=content_type,
                       headers={'Access-Control-Allow-Origin': '*'})
    except Exception as e:
        return Response(f"Error proxying USB camera: {e}", status=502)

@app.route('/api/metrics')
def api_metrics():
    """API endpoint for metrics data"""
    metrics = {
        'cpu_temperature': get_cpu_temp(),
        'system': get_system_stats(),
        'i2c_sensors': {
            'bme680': format_bme680_data(sensor_data.get('bme680', {}))
        },
        'camera': format_camera_metadata(sensor_data.get('camera', {})),
        'last_update': sensor_data.get('last_update', 0)
    }

    return jsonify(metrics)

@app.route('/chicken_image')
def chicken_image():
    """Serve chicken logo"""
    from flask import send_from_directory
    return send_from_directory('static/images', 'chicken_of_despair.png')

@app.route('/usb_test')
def usb_test():
    """USB camera test page"""
    from flask import send_from_directory
    return send_from_directory('static', 'usb_test.html')

@app.route('/csi_test')
def csi_test():
    """CSI camera test page"""
    from flask import send_from_directory
    return send_from_directory('static', 'csi_test.html')

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🐔 BEEPER KEEPER v2.0 - HLS Streaming Edition")
    print("="*60)

    # Initialize MQTT
    print("\n📡 Connecting to MQTT broker...")
    init_mqtt()

    # Give MQTT a moment to connect
    time.sleep(2)

    print("\n✓ Starting web server on http://0.0.0.0:8080")
    print(f"✓ HLS streams available via Flask proxy routes")
    print("\nPress Ctrl+C to stop\n")

    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)
