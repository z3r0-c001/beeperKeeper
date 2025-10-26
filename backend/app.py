#!/usr/bin/env python3
"""
BEEPER KEEPER v2.0 - Streamlined Camera Monitoring System
==========================================================

HLS-based dual camera streaming with BME680 sensor integration
and real-time metrics via MQTT.

Author: z3r0-c001
"""

from flask import Flask, render_template, jsonify, Response, request
import paho.mqtt.client as mqtt
import json
import time
import psutil
import threading
import requests
from datetime import datetime
import uuid
import jwt
from jwt.exceptions import InvalidTokenError
import uuid

app = Flask(__name__)

# Configuration
MQTT_BROKER = "MQTT_BROKER_IP"
MQTT_PORT = 1883
MEDIAMTX_HLS_PORT = 8888
MEDIAMTX_WEBRTC_PORT = 8889

# Global sensor data storage
sensor_data = {
    'bme680': {},
    'camera': {},
    'system': {},
    'cpu_temperature': 0,
    'audio_level': 0,
    'last_update': 0
}

# Active users tracking (ephemeral, in-memory)
# Format: { 'username': {'last_seen': timestamp, 'state': 'viewing'|'away', 'first_seen': timestamp} }
active_users = {}
active_users_lock = threading.Lock()

# Chat messages (ephemeral, in-memory, last 50 messages)
chat_messages = []
chat_lock = threading.Lock()
MAX_CHAT_MESSAGES = 50

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
            ("beeper/camera/csi/metadata", 0),
            ("beeper/audio/level", 0)
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
        elif 'audio/level' in topic:
            sensor_data['audio_level'] = payload.get('level_db', 0)

        sensor_data['last_update'] = time.time()
    except Exception as e:
        print(f"MQTT message error: {e}")

def init_mqtt():
    """Initialize MQTT connection"""
    global mqtt_client
    mqtt_client = mqtt.Client(client_id="MQTT_CLIENT_ID")
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
    if 'goodsupply.farm' in host or 'localhost' in host or '127.0.0.1' in host:
        # Return empty string to use relative URLs (which stay within Cloudflare tunnel)
        return ''
    else:
        # Direct local network access
        return f'http://{request.host.split(":")[0]}:{MEDIAMTX_HLS_PORT}'

def get_webrtc_url():
    """Get WebRTC server URL"""
    host = request.host.split(":")[0]
    return f'http://{host}:{MEDIAMTX_WEBRTC_PORT}'

def get_username_from_jwt():
    """Extract username from Cloudflare Access JWT token"""
    try:
        # Cloudflare Access sends JWT in this header
        jwt_token = request.headers.get('Cf-Access-Jwt-Assertion')

        if not jwt_token:
            # For local testing without Cloudflare, use IP address
            return f"local-{request.remote_addr}"

        # Decode JWT without verification (Cloudflare already verified it)
        # In production, you could verify with Cloudflare's public key
        decoded = jwt.decode(jwt_token, options={"verify_signature": False})

        # Extract email and get username part (before @)
        email = decoded.get('email', '')
        if email:
            username = email.split('@')[0]
            return username

        return f"unknown-{request.remote_addr}"
    except (InvalidTokenError, Exception) as e:
        # Fallback to IP-based identifier
        return f"local-{request.remote_addr}"

def update_user_activity(username, state='viewing'):
    """Update user's last seen timestamp and state"""
    with active_users_lock:
        current_time = time.time()
        if username not in active_users:
            active_users[username] = {
                'first_seen': current_time,
                'last_seen': current_time,
                'state': state
            }
        else:
            active_users[username]['last_seen'] = current_time
            active_users[username]['state'] = state

def cleanup_stale_users():
    """Remove users who haven't sent a heartbeat in 2 minutes"""
    with active_users_lock:
        current_time = time.time()
        stale_threshold = 120  # 2 minutes
        users_to_remove = [
            username for username, data in active_users.items()
            if current_time - data['last_seen'] > stale_threshold
        ]
        for username in users_to_remove:
            del active_users[username]

def get_active_users_list():
    """Get list of active users with their status"""
    cleanup_stale_users()

    with active_users_lock:
        current_time = time.time()
        users_list = []

        for username, data in active_users.items():
            last_seen_seconds = int(current_time - data['last_seen'])
            session_duration = int(current_time - data['first_seen'])

            users_list.append({
                'username': username,
                'state': data['state'],
                'last_seen_seconds': last_seen_seconds,
                'session_duration': session_duration
            })

        # Sort by state (viewing first) then by last_seen
        users_list.sort(key=lambda x: (x['state'] != 'viewing', x['last_seen_seconds']))

        return users_list

@app.route('/')
def index():
    """Main page"""
    base_url = get_base_url()
    webrtc_url = get_webrtc_url()
    return render_template('index.html', hls_base=base_url, webrtc_base=webrtc_url)

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
        'audio_level': sensor_data.get('audio_level', 0),
        'last_update': sensor_data.get('last_update', 0)
    }

    return jsonify(metrics)

@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """User heartbeat endpoint - called every 30 seconds"""
    username = get_username_from_jwt()

    # Get state from request body if provided
    try:
        data = request.get_json() or {}
        state = data.get('state', 'viewing')
    except:
        state = 'viewing'

    update_user_activity(username, state)

    return jsonify({'status': 'ok', 'username': username})

@app.route('/api/user_left', methods=['POST'])
def api_user_left():
    """User departure endpoint - called via beacon on page close"""
    username = get_username_from_jwt()

    # Remove user immediately
    with active_users_lock:
        if username in active_users:
            del active_users[username]

    return '', 204  # No content response for beacon

@app.route('/api/active_users')
def api_active_users():
    """Get list of currently active users"""
    users = get_active_users_list()

    return jsonify({
        'users': users,
        'count': len(users)
    })

@app.route('/api/chat/send', methods=['POST'])
def api_chat_send():
    """Send a chat message"""
    username = get_username_from_jwt()

    try:
        data = request.get_json()
        message = data.get('message', '').strip()

        if not message:
            return jsonify({'error': 'Empty message'}), 400

        # Limit message length
        if len(message) > 500:
            message = message[:500]

        with chat_lock:
            chat_messages.append({
                'id': str(uuid.uuid4()),
                'username': username,
                'message': message,
                'timestamp': time.time()
            })

            # Keep only last 50 messages
            if len(chat_messages) > MAX_CHAT_MESSAGES:
                chat_messages.pop(0)

        return jsonify({'status': 'ok'})

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/chat/delete/<message_id>', methods=['DELETE'])
def api_chat_delete(message_id):
    """Delete a chat message (users can only delete their own messages)"""
    username = get_username_from_jwt()
    
    try:
        with chat_lock:
            # Find the message
            message_to_delete = None
            message_index = None
            
            for idx, msg in enumerate(chat_messages):
                if msg.get('id') == message_id:
                    message_to_delete = msg
                    message_index = idx
                    break
            
            if not message_to_delete:
                return jsonify({'error': 'Message not found'}), 404
            
            # Verify ownership
            if message_to_delete.get('username') != username:
                return jsonify({'error': 'Unauthorized - you can only delete your own messages'}), 403
            
            # Delete the message
            chat_messages.pop(message_index)
            
        return jsonify({'status': 'ok', 'message': 'Message deleted'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/chat/messages')
def api_chat_messages():
    """Get recent chat messages"""
    with chat_lock:
        # Return copy of messages
        messages = list(chat_messages)

    return jsonify({'messages': messages})


@app.route('/api/whoami')
def api_whoami():
    """Return current username"""
    username = get_username_from_jwt()
    return jsonify({'username': username})

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
