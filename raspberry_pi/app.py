#!/usr/bin/env python3
"""
BEEPER KEEPER v2.0 - Streamlined Camera Monitoring System
==========================================================

HLS-based dual camera streaming with BME680 sensor integration
and real-time metrics via MQTT.

Author: z3r0-c001
"""

from flask import Flask, render_template, jsonify, Response, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from markupsafe import escape
from flask_socketio import SocketIO, emit, disconnect
import paho.mqtt.client as mqtt
import json
import time
import psutil
import threading
import requests
from datetime import datetime, timedelta, time as dtime
import jwt
from jwt.exceptions import InvalidTokenError
import pytz
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import cv2
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import subprocess
import queue
from functools import wraps
import tempfile
import eventlet

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

START_TIME = time.time()  # Track service start time for health checks
# Initialize rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10000 per day", "3000 per hour"],
    storage_uri="memory://"
)

# Configuration
MQTT_BROKER = "10.10.10.7"
MQTT_PORT = 1883
MEDIAMTX_HLS_PORT = 8888
MEDIAMTX_WEBRTC_PORT = 8889

# Email/SMTP Configuration (from environment or defaults)
SMTP_ENABLED = os.getenv('GF_SMTP_ENABLED', 'false').lower() == 'true'
SMTP_HOST = os.getenv('GF_SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('GF_SMTP_PORT', '587'))
SMTP_USER = os.getenv('GF_SMTP_USER', '')
SMTP_PASSWORD = os.getenv('GF_SMTP_PASSWORD', '')
SMTP_FROM_ADDRESS = os.getenv('GF_SMTP_FROM_ADDRESS', 'beeper@YOUR_DOMAIN')
SMTP_FROM_NAME = os.getenv('GF_SMTP_FROM_NAME', 'Beeper Keeper Alerts')

# Light schedule times
LIGHTS_ON_TIME = dtime(6, 30)  # 6:30 AM
LIGHTS_OFF_TIME = dtime(19, 0)  # 7:00 PM
ALERT_MINUTES_BEFORE = 15

# Subscription storage file
SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(__file__), 'light_subscriptions.json')

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

# Email alert subscription management
subscriptions_lock = threading.Lock()

# Audio announcement queue
announcement_queue = queue.Queue(maxsize=5)  # Max 5 queued announcements
announcement_lock = threading.Lock()

# Real-time streaming sessions
streaming_sessions = {}
streaming_sessions_lock = threading.Lock()

# ROI image cache (prevents concurrent captures)
roi_image_cache = {
    'image_data': None,
    'timestamp': 0,
    'lock': threading.Lock()
}
ROI_CACHE_DURATION = 30  # seconds (30s for fresher captures)

def load_subscriptions():
    """Load email subscriptions from file"""
    try:
        if os.path.exists(SUBSCRIPTIONS_FILE):
            with open(SUBSCRIPTIONS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error loading subscriptions: {e}")
        return {}

def save_subscriptions(subs):
    """Save email subscriptions to file"""
    try:
        with subscriptions_lock:
            with open(SUBSCRIPTIONS_FILE, 'w') as f:
                json.dump(subs, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving subscriptions: {e}")
        return False

def validate_email(email):
    """Validate email address format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def send_email_alert(to_email, alert_type, alert_on=None, alert_off=None):
    """Send email alert for lights on/off or subscription confirmation

    Args:
        to_email: Recipient email address
        alert_type: Type of alert ('lights_on', 'lights_off', or 'confirmation')
        alert_on: For confirmation emails - whether user subscribed to lights ON alerts
        alert_off: For confirmation emails - whether user subscribed to lights OFF alerts
    """
    if not SMTP_ENABLED:
        print(f"SMTP not enabled, skipping email to {to_email}")
        return False

    try:
        # Calculate target time and compose message based on alert type
        if alert_type == 'confirmation':
            subject = "Beeper Keeper: Subscription Confirmed"

            # Build alert preferences text
            alert_prefs = []
            if alert_on:
                alert_prefs.append("- 15 minutes before lights turn ON (6:15 AM)")
            if alert_off:
                alert_prefs.append("- 15 minutes before lights turn OFF (6:45 PM)")

            alert_list = "\n".join(alert_prefs) if alert_prefs else "- No alerts selected"

            body = f"""
Thank you for subscribing to Beeper Keeper alerts!

You will receive email notifications:
{alert_list}

You can watch the chickens live at: http://10.10.10.28:8080

---

To unsubscribe from these alerts, visit:
http://10.10.10.28:8080/unsubscribe?email={to_email}

Best regards,
Beeper Keeper 10000
🐔
"""
        elif alert_type == 'lights_on':
            target_time = LIGHTS_ON_TIME
            subject = "Beeper Keeper: Lights turning ON in 15 minutes"
            body = f"""
Hello from Beeper Keeper 10000!

This is your scheduled reminder that the coop lights will turn ON in 15 minutes.

Target time: {target_time.strftime('%I:%M %p')}

You can watch the chickens live at: http://10.10.10.28:8080

---

To unsubscribe from these alerts, visit:
http://10.10.10.28:8080/unsubscribe?email={to_email}

Best regards,
Beeper Keeper 10000
🐔
"""
        else:  # lights_off
            target_time = LIGHTS_OFF_TIME
            subject = "Beeper Keeper: Lights turning OFF in 15 minutes"
            body = f"""
Hello from Beeper Keeper 10000!

This is your scheduled reminder that the coop lights will turn OFF in 15 minutes.

Target time: {target_time.strftime('%I:%M %p')}

You can watch the chickens live at: http://10.10.10.28:8080

---

To unsubscribe from these alerts, visit:
http://10.10.10.28:8080/unsubscribe?email={to_email}

Best regards,
Beeper Keeper 10000
🐔
"""

        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_ADDRESS}>"
        msg['To'] = to_email

        # Attach plain text body
        msg.attach(MIMEText(body, 'plain'))

        # Connect and send
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✓ Sent {alert_type} email to {to_email}")
        return True

    except Exception as e:
        print(f"✗ Failed to send email to {to_email}: {e}")
        return False

def send_scheduled_alerts(alert_type):
    """Send alerts to all subscribed users for a given alert type"""
    subscriptions = load_subscriptions()

    if not subscriptions:
        print(f"No subscriptions found for {alert_type}")
        return

    alert_key = f'alert_{alert_type}'

    for email, prefs in subscriptions.items():
        if prefs.get(alert_key, False):
            print(f"Sending {alert_type} alert to {email}")
            send_email_alert(email, alert_type)

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
            ("beeper/audio/level", 0),
            ("beeper/water/tank", 0),
            ("beeper/water/status", 0),
            ("beeper/feed/level/current", 0),
            ("beeper/feed/level/all", 0),
            ("beeper/weather/all", 0)
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
            elif topic.endswith('/iaq_bsec'):
                # Capture BSEC IAQ accuracy data (0-3 scale)
                if 'bme680' not in sensor_data:
                    sensor_data['bme680'] = {}
                sensor_data['bme680']['iaq_accuracy'] = payload.get('accuracy', 0)
        elif 'cpu/temperature' in topic:
            sensor_data['cpu_temperature'] = payload.get('cpu_temp', 0)
        elif 'system/stats' in topic:
            sensor_data['system'] = payload
        elif 'camera/csi/metadata' in topic:
            sensor_data['camera'] = payload
        elif 'audio/level' in topic:
            sensor_data['audio_level'] = payload.get('level_db', 0)
        elif 'water/tank' in topic:
            # Initialize water dict if it doesn't exist, then merge tank data
            if 'water' not in sensor_data:
                sensor_data['water'] = {}
            sensor_data['water'].update(payload)
        elif 'water/status' in topic:
            # Initialize water dict if it doesn't exist, then merge status data
            if 'water' not in sensor_data:
                sensor_data['water'] = {}
            sensor_data['water'].update(payload)
        elif 'feed/level/current' in topic:
            # Food level data from MQTT (raw float value, not JSON object)
            if 'food' not in sensor_data:
                sensor_data['food'] = {}
            # Handle both float and dict payloads
            if isinstance(payload, dict):
                sensor_data['food'].update(payload)
            else:
                sensor_data['food']['percentage'] = float(payload)
        elif 'feed/level/all' in topic:
            # Full feed level data with level classification
            sensor_data['food'] = {
                'percentage': payload.get('percent_full', 0),
                'level': payload.get('level', 'UNKNOWN'),
                'confidence': payload.get('confidence', 0),
                'method': payload.get('method', 'unknown')
            }
        elif 'weather/all' in topic:
            # Weather data from NWS API
            sensor_data['weather'] = payload

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
        # Use interval=0 for non-blocking CPU measurement (uses cached value)
        # This prevents /api/metrics from blocking for 0.5s on every request
        cpu_percent = round(psutil.cpu_percent(interval=0), 1)
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
    """Format BME680 sensor data for display with BSEC calibration status"""
    if not data:
        return {}

    # BSEC accuracy: 0=stabilizing, 1=low, 2=medium, 3=high (calibrated)
    iaq_accuracy = data.get('iaq_accuracy', 0)

    # Map accuracy to calibration status
    # Accuracy < 3 means still calibrating (4-day BSEC calibration period)
    calibrating = iaq_accuracy < 3

    # Get calibration progress from MQTT data (calculated by mqtt_publisher using BSEC)
    calibration_progress = data.get('calibration_progress', 0) or 0

    # Calculate calibration day from progress (0-100% over 4 days)
    # Progress: 0-25% = Day 1, 25-50% = Day 2, 50-75% = Day 3, 75-100% = Day 4
    if calibration_progress < 25:
        calibration_day = 1
        calibration_day_label = f"Day 1 of 4 ({calibration_progress:.1f}%)"
    elif calibration_progress < 50:
        calibration_day = 2
        calibration_day_label = f"Day 2 of 4 ({calibration_progress:.1f}%)"
    elif calibration_progress < 75:
        calibration_day = 3
        calibration_day_label = f"Day 3 of 4 ({calibration_progress:.1f}%)"
    elif calibration_progress < 100:
        calibration_day = 4
        calibration_day_label = f"Day 4 of 4 ({calibration_progress:.1f}%)"
    else:
        calibration_day = 4
        calibration_day_label = "Calibrated"

    # Base sensor readings (always available)
    result = {
        'temperature': round(data.get('temperature', 0), 1),
        'humidity': round(data.get('humidity', 0), 1),
        'pressure': round(data.get('pressure', 0), 1),
        'gas_raw': int(data.get('gas_raw', 0)),
        'iaq_accuracy': iaq_accuracy,
        'calibration_progress': calibration_progress,
        'calibration_day': calibration_day,
        'calibration_day_label': calibration_day_label
    }

    if calibrating:
        # Show calibrating status with progress
        result['calibration_status'] = 'calibrating'
    else:
        # Calibration complete (accuracy = 3), show full IAQ data
        result['calibration_status'] = 'ready'

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

        result['iaq'] = round(data.get('iaq', 0), 1) if data.get('iaq') else None
        result['iaq_classification'] = iaq_class
        result['co2_equivalent'] = int(data.get('co2_equivalent', 0)) if data.get('co2_equivalent') else None

    return result

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
    """Always use relative URLs to ensure Flask proxy handles all streams"""
    # Return empty string for all access (local and external)
    # This ensures consistent behavior: all HLS requests go through Flask proxy -> MediaMTX
    return ''

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

def get_authenticated_username():
    """Get authenticated username from JWT token for current request"""
    jwt_token = request.headers.get('Cf-Access-Jwt-Assertion')

    if not jwt_token:
        # Allow local development without JWT
        if request.remote_addr.startswith('10.10.10.') or request.remote_addr == '127.0.0.1':
            return f"local-{request.remote_addr}"
        return None

    try:
        decoded = jwt.decode(jwt_token, options={"verify_signature": False})
        email = decoded.get('email', '')
        if email:
            return email
        return None
    except:
        return None

def require_local_network(f):
    """Decorator: Require @YOUR_DOMAIN authenticated user"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        jwt_token = request.headers.get('Cf-Access-Jwt-Assertion')

        if not jwt_token:
            # Allow local development without JWT
            if request.remote_addr.startswith('10.10.10.') or request.remote_addr == '127.0.0.1':
                print("⚠ Local access - skipping auth check")
                return f(*args, **kwargs)
            return jsonify({'error': 'Authentication required'}), 401

        try:
            decoded = jwt.decode(jwt_token, options={"verify_signature": False})
            email = decoded.get('email', '')

            # Allowed emails: @YOUR_DOMAIN domain + specific authorized users
            ALLOWED_EMAILS = [
                'user1@example.com',
                'user2@example.com'
            ]

            if not email or (not email.endswith('@YOUR_DOMAIN') and email not in ALLOWED_EMAILS):
                print(f"✗ Access denied for {email}")
                return jsonify({'error': 'Access denied - authorization required'}), 403

            print(f"✓ Announcement access granted: {email}")
            return f(*args, **kwargs)

        except Exception as e:
            print(f"✗ JWT validation error: {e}")
            return jsonify({'error': f'Invalid token: {str(e)}'}), 401

    return decorated_function

def play_announcement(audio_data, sample_rate=16000):
    """Play audio announcement via ALSA (blocking)

    Args:
        audio_data: bytes - PCM audio data (S16_LE format)
        sample_rate: int - Sample rate (default 16kHz)

    Returns:
        bool - True if playback succeeded
    """
    tmp_path = None
    try:
        # Write to temp file (aplay requires file input)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(audio_data)

        # Play via aplay with explicit ALSA device
        result = subprocess.run([
            'aplay',
            '-D', 'plughw:E4K',  # EMEET speaker via dmix (allows simultaneous playback)
            '-f', 'S16_LE',  # 16-bit signed little-endian
            '-r', str(sample_rate),  # Sample rate
            '-c', '1',  # Mono
            tmp_path
        ], capture_output=True, timeout=30)

        # Cleanup temp file
        os.unlink(tmp_path)

        if result.returncode == 0:
            print(f"✓ Announcement played successfully ({len(audio_data)} bytes)")
            return True
        else:
            print(f"✗ Playback failed: {result.stderr.decode()}")
            return False

    except subprocess.TimeoutExpired:
        print("✗ Playback timeout (>30s)")
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return False
    except Exception as e:
        print(f"✗ Playback error: {e}")
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return False

def announcement_queue_worker():
    """Background thread: consume announcement queue and play audio"""
    print("✓ Announcement queue worker started")

    while True:
        try:
            # Block until announcement available
            audio_data, username = announcement_queue.get(timeout=1)

            print(f"🔊 Playing announcement from {username} ({len(audio_data)} bytes)")

            # Convert WebM/Opus to PCM WAV before playback
            webm_path = None
            wav_path = None
            try:
                # Write WebM data to temp file
                with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as webm_file:
                    webm_path = webm_file.name
                    webm_file.write(audio_data)

                # Create output WAV path
                wav_path = tempfile.mktemp(suffix='.wav')

                # Convert WebM/Opus → WAV (PCM S16_LE, 48kHz, mono)
                result = subprocess.run([
                    'ffmpeg',
                    '-i', webm_path,
                    '-ar', '48000',      # 48kHz sample rate (USB speaker native rate)
                    '-ac', '1',          # Mono
                    '-f', 's16le',       # PCM signed 16-bit little-endian
                    '-af', 'volume=30dB',      # 20dB gain for audibility
                    '-acodec', 'pcm_s16le',  # PCM codec
                    '-y',                # Overwrite output
                    wav_path
                ], capture_output=True, timeout=10)

                # Cleanup WebM temp file
                if webm_path and os.path.exists(webm_path):
                    os.unlink(webm_path)
                    webm_path = None

                if result.returncode != 0:
                    print(f"✗ Audio conversion failed: {result.stderr.decode()}")
                    announcement_queue.task_done()
                    continue

                # Read converted PCM data
                with open(wav_path, 'rb') as f:
                    pcm_data = f.read()

                # Cleanup WAV temp file
                if wav_path and os.path.exists(wav_path):
                    os.unlink(wav_path)
                    wav_path = None

                print(f"✓ Converted WebM ({len(audio_data)} bytes) → PCM ({len(pcm_data)} bytes)")

                # Play announcement (blocking)
                success = play_announcement(pcm_data, sample_rate=48000)

                announcement_queue.task_done()

                if not success:
                    print(f"⚠ Announcement playback failed for {username}")

            except subprocess.TimeoutExpired:
                print("✗ Audio conversion timeout")
                announcement_queue.task_done()
            except Exception as conv_error:
                print(f"✗ Audio conversion error: {conv_error}")
                announcement_queue.task_done()
            finally:
                # Ensure temp files are cleaned up
                if webm_path and os.path.exists(webm_path):
                    os.unlink(webm_path)
                if wav_path and os.path.exists(wav_path):
                    os.unlink(wav_path)

        except queue.Empty:
            continue  # No announcements, keep waiting
        except Exception as e:
            print(f"✗ Queue worker error: {e}")

def cleanup_stream(session_id):
    """Clean up streaming session"""
    with streaming_sessions_lock:
        session = streaming_sessions.pop(session_id, None)

        if session:
            try:
                session['ffmpeg'].stdin.close()
                session['ffmpeg'].wait(timeout=2)
            except:
                session['ffmpeg'].kill()

            try:
                session['aplay'].wait(timeout=2)
            except:
                session['aplay'].kill()

            # Close and convert recording file
            if session.get('recording_file'):
                try:
                    session['recording_file'].close()
                    print("✓ Recording file closed")

                    # Convert WebM to WAV for easy playback
                    recording_path = session.get('recording_path')
                    if recording_path and os.path.exists(recording_path):
                        wav_path = recording_path.replace('.webm', '.wav')
                        result = subprocess.run([
                            'ffmpeg', '-y', '-i', recording_path,
                            '-acodec', 'pcm_s16le', '-ar', '48000', '-ac', '1',
                            wav_path
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                        if result.returncode == 0:
                            print(f"✓ Announcement saved to {wav_path}")
                            print(f"  Download: scp pi_user@10.10.10.28:{wav_path} ~/Desktop/")

                            # Delete .webm immediately (intermediate file)
                            try:
                                if os.path.exists(recording_path):
                                    os.remove(recording_path)
                                    print("🗑️ Cleaned up .webm file")
                            except Exception as e:
                                print(f"⚠️ Error removing .webm: {e}")
                        else:
                            print(f"⚠ Failed to convert recording to WAV")
                except Exception as e:
                    print(f"⚠ Error closing recording file: {e}")

# WebSocket Event Handlers for Real-Time Streaming

@socketio.on('connect', namespace='/announce_stream')
def handle_stream_connect():
    """Client connected for streaming"""
    username = get_authenticated_username()
    if not username or not (username.endswith('@YOUR_DOMAIN') or username.startswith('local-') or
                           username in ['user1@example.com', 'user2@example.com']):
        disconnect()
        return False

    print(f"🎙️ Streaming connection from {username}")
    emit('ready', {'status': 'ready'})

@socketio.on('start_stream', namespace='/announce_stream')
def handle_start_stream(data=None):
    """Start audio streaming session"""
    username = get_authenticated_username()

    with streaming_sessions_lock:
        if len(streaming_sessions) >= 5:
            emit('error', {'error': 'Too many active streams'})
            return

        # Create recording file to save announcement for verification
        from datetime import datetime
        timestamp_str = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        recording_path = f'/tmp/announcement_{timestamp_str}.webm'
        try:
            recording_file = open(recording_path, 'wb')
            print(f"✓ Recording announcement to {recording_path}")
        except Exception as e:
            print(f"⚠ Could not create recording file: {e}")
            recording_file = None

        # Create ffmpeg subprocess for real-time playback
        ffmpeg_proc = subprocess.Popen([
            'ffmpeg',
            '-f', 'webm',
            '-i', 'pipe:0',
            '-ar', '48000',
            '-ac', '1',
            '-f', 's16le',
            '-af', 'volume=30dB',
            '-acodec', 'pcm_s16le',
            'pipe:1'
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Create aplay subprocess
        aplay_proc = subprocess.Popen([
            'aplay',
            '-D', 'plughw:E4K',
            '-f', 'S16_LE',
            '-r', '48000',
            '-c', '1'
        ], stdin=ffmpeg_proc.stdout)

        streaming_sessions[request.sid] = {
            'username': username,
            'ffmpeg': ffmpeg_proc,
            'aplay': aplay_proc,
            'start_time': time.time(),
            'bytes_received': 0,
            'recording_file': recording_file,
            'recording_path': recording_path
        }

    emit('streaming', {'status': 'streaming'})
    print(f"▶️ Started stream from {username}")

@socketio.on('audio_chunk', namespace='/announce_stream')
def handle_audio_chunk(data):
    """Receive and play audio chunk in real-time"""
    session = streaming_sessions.get(request.sid)

    if not session:
        emit('error', {'error': 'No active stream'})
        return

    try:
        # Write chunk to ffmpeg stdin
        session['ffmpeg'].stdin.write(data)
        session['ffmpeg'].stdin.flush()
        session['bytes_received'] += len(data)

        # Also save to recording file for verification
        if session.get('recording_file'):
            try:
                session['recording_file'].write(data)
            except Exception as e:
                print(f"⚠ Error writing to recording file: {e}")
    except Exception as e:
        print(f"❌ Stream error: {e}")
        emit('error', {'error': str(e)})
        cleanup_stream(request.sid)

@socketio.on('stop_stream', namespace='/announce_stream')
def handle_stop_stream():
    """Stop streaming and cleanup"""
    session = streaming_sessions.get(request.sid)

    if session:
        duration = time.time() - session['start_time']
        print(f"⏹️ Stream stopped from {session['username']} ({session['bytes_received']} bytes, {duration:.1f}s)")
        cleanup_stream(request.sid)
        emit('stopped', {'status': 'completed'})

@socketio.on('disconnect', namespace='/announce_stream')
def handle_stream_disconnect():
    """Client disconnected, cleanup"""
    cleanup_stream(request.sid)

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
@limiter.exempt
def proxy_csi_camera(subpath):
    """Proxy CSI camera HLS stream with proper connection management"""
    try:
        url = f'http://localhost:{MEDIAMTX_HLS_PORT}/csi_camera/{subpath}'

        def generate():
            """Generator that properly closes connection after streaming"""
            resp = None
            try:
                resp = requests.get(url, stream=True, timeout=10)
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                if resp is not None:
                    resp.close()

        # Get content type by making a head request
        try:
            head_resp = requests.head(url, timeout=2)
            content_type = head_resp.headers.get('Content-Type', 'application/vnd.apple.mpegurl')
        except:
            content_type = 'application/vnd.apple.mpegurl'

        return Response(generate(),
                       content_type=content_type,
                       headers={
                           'Access-Control-Allow-Origin': request.headers.get('Origin', '*'),
                           'Access-Control-Allow-Credentials': 'true',
                           'Cache-Control': 'no-cache, no-store, must-revalidate',
                           'Pragma': 'no-cache',
                           'Expires': '0'
                       })
    except Exception as e:
        return Response(f"Error proxying CSI camera: {e}", status=502)

@app.route('/usb_camera/<path:subpath>')
@limiter.exempt
def proxy_usb_camera(subpath):
    """Proxy USB camera HLS stream with proper connection management"""
    try:
        url = f'http://localhost:{MEDIAMTX_HLS_PORT}/usb_camera/{subpath}'

        def generate():
            """Generator that properly closes connection after streaming"""
            resp = None
            try:
                resp = requests.get(url, stream=True, timeout=10)
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                if resp is not None:
                    resp.close()

        # Get content type by making a head request
        try:
            head_resp = requests.head(url, timeout=2)
            content_type = head_resp.headers.get('Content-Type', 'application/vnd.apple.mpegurl')
        except:
            content_type = 'application/vnd.apple.mpegurl'

        return Response(generate(),
                       content_type=content_type,
                       headers={
                           'Access-Control-Allow-Origin': request.headers.get('Origin', '*'),
                           'Access-Control-Allow-Credentials': 'true',
                           'Cache-Control': 'no-cache, no-store, must-revalidate',
                           'Pragma': 'no-cache',
                           'Expires': '0'
                       })
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
        'water': sensor_data.get('water', {}),
        'food': sensor_data.get('food', {}),
        'weather': sensor_data.get('weather', {}),
        'last_update': sensor_data.get('last_update', 0)
    }

    return jsonify(metrics)

@app.route('/api/heartbeat', methods=['POST'])
@limiter.limit("120 per minute")
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
@limiter.limit("10 per minute")
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
@limiter.limit("30 per minute")
def api_chat_send():
    """Send a chat message"""
    username = get_username_from_jwt()

    try:
        data = request.get_json()
        message = data.get('message', '').strip()

        if not message:
            return jsonify({'error': 'Empty message'}), 400

        # Sanitize message to prevent XSS
        message = str(escape(message))

        # Limit message length
        if len(message) > 500:
            message = message[:500]

        with chat_lock:
            chat_messages.append({
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

@app.route('/api/chat/messages')
def api_chat_messages():
    """Get recent chat messages"""
    with chat_lock:
        # Return copy of messages
        messages = list(chat_messages)

    return jsonify({'messages': messages})

@app.route("/api/lights_countdown")
@limiter.exempt
def lights_countdown():
    """API endpoint for lights countdown timer"""
    try:
        est = pytz.timezone("America/New_York")
        now = datetime.now(est)

        # Define light schedule
        lights_out_time = dtime(19, 0)
        lights_on_time = dtime(6, 30)

        # Create datetime objects
        lights_out = now.replace(hour=19, minute=0, second=0, microsecond=0)
        lights_on = now.replace(hour=6, minute=30, second=0, microsecond=0)

        # Determine current phase and target
        current_time = now.time()

        if lights_on_time <= current_time < lights_out_time:
            target = lights_out
            label = "COUNTDOWN TO LIGHTS OUT"
            phase = "day"
            emoji = "🌙"
        else:
            if current_time >= lights_out_time:
                lights_on += timedelta(days=1)
            target = lights_on
            label = "COUNTDOWN TO LIGHTS ON"
            phase = "night"
            emoji = "☀️"

        # Calculate time difference
        diff = target - now
        total_seconds = int(diff.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        # Calculate progress
        if phase == "day":
            day_start = now.replace(hour=6, minute=30, second=0, microsecond=0)
            day_duration = (lights_out - day_start).total_seconds()
            elapsed = (now - day_start).total_seconds()
            progress = (elapsed / day_duration) * 100 if day_duration > 0 else 0
        else:
            night_start = now.replace(hour=19, minute=0, second=0, microsecond=0)
            if current_time < lights_on_time:
                night_start -= timedelta(days=1)
            night_duration = (lights_on - night_start).total_seconds()
            elapsed = (now - night_start).total_seconds()
            progress = (elapsed / night_duration) * 100 if night_duration > 0 else 0

        progress = max(0, min(100, progress))

        return jsonify({
            "label": label, "emoji": emoji, "phase": phase,
            "hours": hours, "minutes": minutes, "seconds": seconds,
            "total_seconds": total_seconds, "progress": round(progress, 1),
            "target_time": target.strftime("%I:%M %p"),
            "current_time": now.strftime("%I:%M:%S %p"),
            "timestamp": now.isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/lights/alerts/subscribe', methods=['POST'])
@limiter.limit("10 per hour")
def api_subscribe_alerts():
    """Subscribe to light change email alerts"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        alert_on = data.get('alert_on', False)
        alert_off = data.get('alert_off', False)

        # Validate email
        if not email:
            return jsonify({'error': 'Email address is required'}), 400

        if not validate_email(email):
            return jsonify({'error': 'Invalid email address format'}), 400

        # Check if at least one alert is selected
        if not alert_on and not alert_off:
            return jsonify({'error': 'Please select at least one alert type'}), 400

        # Load existing subscriptions
        subscriptions = load_subscriptions()

        # Add or update subscription
        subscriptions[email] = {
            'alert_lights_on': alert_on,
            'alert_lights_off': alert_off,
            'subscribed_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }

        # Save subscriptions
        if not save_subscriptions(subscriptions):
            return jsonify({'error': 'Failed to save subscription'}), 500

        print(f"✓ New subscription: {email} (on={alert_on}, off={alert_off})")

        # Send confirmation email (non-blocking - don't fail subscription if email fails)
        try:
            send_email_alert(email, 'confirmation', alert_on=alert_on, alert_off=alert_off)
        except Exception as e:
            # Log error but don't block the subscription
            print(f"⚠ Failed to send confirmation email to {email}: {e}")

        return jsonify({
            'status': 'success',
            'message': 'Successfully subscribed to light alerts',
            'email': email,
            'alerts': {
                'lights_on': alert_on,
                'lights_off': alert_off
            }
        })

    except Exception as e:
        print(f"Subscription error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/lights/alerts/unsubscribe', methods=['POST'])
@limiter.limit("10 per hour")
def api_unsubscribe_alerts():
    """Unsubscribe from light change email alerts"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()

        if not email:
            return jsonify({'error': 'Email address is required'}), 400

        # Load existing subscriptions
        subscriptions = load_subscriptions()

        # Remove subscription if exists
        if email in subscriptions:
            del subscriptions[email]
            save_subscriptions(subscriptions)
            print(f"✓ Unsubscribed: {email}")
            return jsonify({
                'status': 'success',
                'message': 'Successfully unsubscribed from alerts'
            })
        else:
            return jsonify({
                'status': 'not_found',
                'message': 'Email not found in subscriptions'
            }), 404

    except Exception as e:
        print(f"Unsubscribe error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/lights/alerts/check', methods=['GET'])
def api_check_subscription():
    """Check if an email is subscribed (for UI state)"""
    try:
        email = request.args.get('email', '').strip().lower()

        if not email:
            return jsonify({'subscribed': False})

        subscriptions = load_subscriptions()

        if email in subscriptions:
            return jsonify({
                'subscribed': True,
                'alerts': subscriptions[email]
            })
        else:
            return jsonify({'subscribed': False})

    except Exception as e:
        print(f"Check subscription error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/unsubscribe')
def unsubscribe_page():
    """Unsubscribe page - accessible via email link"""
    email = request.args.get('email', '').strip().lower()

    # Check if email is provided and valid
    if email and validate_email(email):
        # Check if email is subscribed
        subscriptions = load_subscriptions()

        if email in subscriptions:
            # Show unsubscribe confirmation page
            return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Unsubscribe - Beeper Keeper</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: #f1f5f9;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 40px;
            max-width: 500px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            border: 2px solid #14b8a6;
            text-align: center;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 20px;
            color: #60a5fa;
        }}
        p {{
            font-size: 1.1rem;
            margin-bottom: 30px;
            line-height: 1.6;
        }}
        .email {{
            background: rgba(255,255,255,0.1);
            padding: 10px;
            border-radius: 6px;
            margin: 20px 0;
            font-weight: bold;
            color: #14b8a6;
        }}
        button {{
            padding: 15px 40px;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            margin: 10px;
        }}
        .btn-unsubscribe {{
            background: #ef4444;
            color: white;
        }}
        .btn-unsubscribe:hover {{
            background: #dc2626;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
        }}
        .btn-cancel {{
            background: #cbd5e1;
            color: #0f172a;
        }}
        .btn-cancel:hover {{
            background: #94a3b8;
        }}
        #message {{
            display: none;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
        }}
        .success {{
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
            border: 1px solid #10b981;
        }}
        .error {{
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            border: 1px solid #ef4444;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🐔 Beeper Keeper</h1>
        <h2>Unsubscribe from Alerts</h2>

        <p>Are you sure you want to unsubscribe from Beeper Keeper light alerts?</p>

        <div class="email">{email}</div>

        <div id="confirmButtons">
            <button class="btn-unsubscribe" onclick="confirmUnsubscribe()">Yes, Unsubscribe</button>
            <button class="btn-cancel" onclick="window.close()">Cancel</button>
        </div>

        <div id="message"></div>
    </div>

    <script>
        function confirmUnsubscribe() {{
            const buttons = document.getElementById('confirmButtons');
            const message = document.getElementById('message');

            buttons.style.display = 'none';
            message.textContent = 'Unsubscribing...';
            message.style.display = 'block';

            fetch('/api/lights/alerts/unsubscribe', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{ email: '{email}' }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.status === 'success') {{
                    message.textContent = 'Successfully unsubscribed! You will no longer receive light alert emails.';
                    message.className = 'success';
                }} else {{
                    message.textContent = 'Error: ' + (data.message || 'Could not unsubscribe');
                    message.className = 'error';
                    buttons.style.display = 'block';
                }}
            }})
            .catch(error => {{
                message.textContent = 'Network error. Please try again.';
                message.className = 'error';
                buttons.style.display = 'block';
            }});
        }}
    </script>
</body>
</html>
"""
        else:
            # Email not found
            return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Not Found - Beeper Keeper</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: #f1f5f9;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 40px;
            max-width: 500px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            border: 2px solid #14b8a6;
            text-align: center;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 20px;
            color: #60a5fa;
        }}
        p {{
            font-size: 1.1rem;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🐔 Beeper Keeper</h1>
        <h2>Email Not Found</h2>
        <p>This email address is not currently subscribed to alerts.</p>
    </div>
</body>
</html>
"""
    else:
        # Invalid email
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Invalid Request - Beeper Keeper</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: #f1f5f9;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 40px;
            max-width: 500px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            border: 2px solid #14b8a6;
            text-align: center;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 20px;
            color: #60a5fa;
        }}
        p {{
            font-size: 1.1rem;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🐔 Beeper Keeper</h1>
        <h2>Invalid Request</h2>
        <p>Please use the unsubscribe link provided in your alert emails.</p>
    </div>
</body>
</html>
"""

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

@app.route('/api/announce', methods=['POST'])
@limiter.limit("10 per minute")  # Rate limit: 10 announcements/minute
@require_local_network
def api_announce():
    """Receive audio announcement from authenticated user"""
    username = get_username_from_jwt()

    try:
        # Get audio data from request
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400

        audio_file = request.files['audio']
        audio_data = audio_file.read()

        # Validate audio size (max 30 seconds @ 16kHz mono = 960KB)
        MAX_SIZE = 1_000_000  # 1MB limit
        if len(audio_data) > MAX_SIZE:
            return jsonify({'error': f'Audio too long (max 30s / 1MB)'}), 400

        if len(audio_data) < 1000:
            return jsonify({'error': 'Audio too short'}), 400

        # Add to queue (non-blocking)
        try:
            announcement_queue.put_nowait((audio_data, username))
            queue_size = announcement_queue.qsize()

            print(f"✓ Announcement queued from {username} ({len(audio_data)} bytes, queue size: {queue_size})")

            return jsonify({
                'status': 'queued',
                'message': 'Announcement will play shortly',
                'queue_position': queue_size,
                'username': username
            })

        except queue.Full:
            return jsonify({'error': 'Announcement queue full (max 5), try again later'}), 503

    except Exception as e:
        print(f"✗ Announce error: {e}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

# Start announcement queue worker thread
worker_thread = threading.Thread(target=announcement_queue_worker, daemon=True)
worker_thread.start()


@app.route("/grafana/<path:subpath>")
def proxy_grafana(subpath):
    """Proxy Grafana dashboard to avoid CORS/iframe issues"""
    try:
        grafana_url = f"http://10.10.10.7:3000/{subpath}"

        # Forward the request to Grafana
        resp = requests.get(
            grafana_url,
            params=request.args,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            stream=True,
            timeout=30
        )

        # Create response with Grafana content
        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        # Forward response with appropriate headers
        response = Response(generate(), status=resp.status_code)

        # Copy relevant headers from Grafana response
        for key, value in resp.headers.items():
            if key.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                response.headers[key] = value

        # Allow iframe embedding from same origin
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"

        return response

    except Exception as e:
        print(f"Grafana proxy error: {e}")
        return jsonify({"error": "Grafana unavailable"}), 502



# ============================================================================
# FEED TRAINING ROUTES - ML Calibration & Training Data Collection
# ============================================================================

# Calibration data directory
CALIBRATION_DATA_DIR = '/opt/beeperKeeper/calibration_data'
TRAINING_DATA_DIR = '/opt/beeperKeeper/feed_training_data'
TRAINING_IMAGES_DIR = os.path.join(TRAINING_DATA_DIR, 'images')
TRAINING_LABELS_DIR = os.path.join(TRAINING_DATA_DIR, 'labels')

# Ensure directories exist
os.makedirs(CALIBRATION_DATA_DIR, exist_ok=True)
os.makedirs(TRAINING_IMAGES_DIR, exist_ok=True)
os.makedirs(TRAINING_LABELS_DIR, exist_ok=True)

@app.route('/train-feed')
def train_feed():
    """Serve the feed training interface"""
    return render_template('train_feed.html')

@app.route('/api/feed/calibration')
def get_feed_calibration():
    """Get current feed calibration values from feed_config.py"""
    try:
        # Import current config to get live values
        import re
        config_path = '/opt/beeperKeeper/feed_config.py'

        # Read feed_config.py and extract FEED_LEVEL_FULL_Y and FEED_LEVEL_EMPTY_Y
        with open(config_path, 'r') as f:
            config_content = f.read()

        # Parse values using regex
        full_y_match = re.search(r'FEED_LEVEL_FULL_Y\s*=\s*(\d+)', config_content)
        empty_y_match = re.search(r'FEED_LEVEL_EMPTY_Y\s*=\s*(\d+)', config_content)

        full_y = int(full_y_match.group(1)) if full_y_match else 0
        empty_y = int(empty_y_match.group(1)) if empty_y_match else 0

        return jsonify({
            'full_y': full_y,
            'empty_y': empty_y,
            'range': abs(empty_y - full_y)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/feed/roi-image')
@limiter.limit("6 per minute")
def get_feed_roi_image():
    """
    Extract and return the current ROI from the feed monitor image.

    This captures a fresh image from the CSI camera, extracts the ROI,
    and returns it as a JPEG for the training interface.

    Uses 30-second caching to prevent concurrent capture attempts that
    would cause MediaMTX restart storms and camera lock conflicts.
    """
    with roi_image_cache['lock']:
        current_time = time.time()

        # Check if user explicitly requests fresh capture
        force_fresh = request.args.get('force_fresh', 'false').lower() == 'true'
        cache_age = current_time - roi_image_cache['timestamp']

        # Return cached image if:
        # 1. Cache exists AND
        # 2. Cache is less than 30 seconds old AND
        # 3. User didn't request force_fresh
        if (roi_image_cache['image_data'] is not None and
            cache_age < ROI_CACHE_DURATION and
            not force_fresh):
            print(f"✓ Serving cached ROI image (age: {int(cache_age)}s)")
            return Response(roi_image_cache['image_data'], mimetype='image/jpeg')

        # Need fresh capture
        print(f"⚡ Capturing fresh ROI image (force_fresh={force_fresh}, cache_age={int(cache_age)}s)...")

        try:
            # Import feed_config to get ROI coordinates
            import sys
            from io import BytesIO
            from PIL import Image

            sys.path.insert(0, '/opt/beeperKeeper')
            from feed_config import ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT, IMAGE_PATH

            # Trigger a fresh image capture using the feed monitor's capture script
            # This calls capture_feed_still.sh which handles MediaMTX coordination
            capture_script = '/opt/beeperKeeper/capture_feed_still.sh'

            result = subprocess.run(
                [capture_script],
                capture_output=True,
                text=True,
                timeout=20
            )

            if result.returncode != 0:
                print(f"✗ Capture script failed: {result.stderr}")
                return jsonify({'error': 'Image capture failed'}), 500

            # Load the captured image
            if not os.path.exists(IMAGE_PATH):
                print(f"✗ Image file not found: {IMAGE_PATH}")
                return jsonify({'error': 'Image file not found'}), 500

            image = cv2.imread(IMAGE_PATH)
            if image is None:
                print(f"✗ Could not load image from {IMAGE_PATH}")
                return jsonify({'error': 'Could not load image'}), 500

            # Extract ROI
            roi = image[ROI_Y:ROI_Y+ROI_HEIGHT, ROI_X:ROI_X+ROI_WIDTH]

            # Convert BGR (OpenCV) to RGB (PIL)
            roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)

            # Convert to PIL Image
            pil_image = Image.fromarray(roi_rgb)

            # Save to BytesIO buffer as JPEG
            buffer = BytesIO()
            pil_image.save(buffer, format='JPEG', quality=95)
            roi_jpeg = buffer.getvalue()

            # Cache the result
            roi_image_cache['image_data'] = roi_jpeg
            roi_image_cache['timestamp'] = current_time

            print(f"✓ Fresh ROI image captured and cached ({len(roi_jpeg)} bytes)")
            return Response(roi_jpeg, mimetype='image/jpeg')

        except subprocess.TimeoutExpired:
            print("✗ Image capture timeout (>20s)")
            return jsonify({'error': 'Image capture timeout'}), 500
        except Exception as e:
            print(f"✗ ROI image error: {e}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/feed/save-calibration', methods=['POST'])
def save_feed_calibration():
    """
    Save new calibration markers to feed_config.py.

    Expects JSON: { "full_y": int, "empty_y": int }

    This updates the FEED_LEVEL_FULL_Y and FEED_LEVEL_EMPTY_Y values
    in feed_config.py and restarts the feed-monitor service.
    """
    try:
        import re

        data = request.get_json()
        full_y = int(data.get('full_y', 0))
        empty_y = int(data.get('empty_y', 0))

        if full_y >= empty_y:
            return jsonify({
                'success': False,
                'error': 'FULL_Y must be less than EMPTY_Y (Y increases downward)'
            }), 400

        # Read current feed_config.py
        config_path = '/opt/beeperKeeper/feed_config.py'
        with open(config_path, 'r') as f:
            config_content = f.read()

        # Update FEED_LEVEL_FULL_Y value
        config_content = re.sub(
            r'FEED_LEVEL_FULL_Y\s*=\s*\d+',
            f'FEED_LEVEL_FULL_Y = {full_y}',
            config_content
        )

        # Update FEED_LEVEL_EMPTY_Y value
        config_content = re.sub(
            r'FEED_LEVEL_EMPTY_Y\s*=\s*\d+',
            f'FEED_LEVEL_EMPTY_Y = {empty_y}',
            config_content
        )

        # Update calibration date and version
        today = datetime.now().strftime('%Y-%m-%d')
        config_content = re.sub(
            r"CALIBRATION_DATE\s*=\s*['\"].*?['\"]",
            f"CALIBRATION_DATE = '{today}'",
            config_content
        )

        # Write updated config
        with open(config_path, 'w') as f:
            f.write(config_content)

        # Also save to calibration_data directory for record-keeping
        calibration_record = {
            'full_y': full_y,
            'empty_y': empty_y,
            'range': empty_y - full_y,
            'timestamp': datetime.now().isoformat(),
            'method': 'web_ui_manual'
        }

        record_path = os.path.join(
            CALIBRATION_DATA_DIR,
            f'calibration_{today}.json'
        )
        with open(record_path, 'w') as f:
            json.dump(calibration_record, f, indent=2)

        # Restart feed-monitor service to apply new calibration
        restart_result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'feed-monitor'],
            capture_output=True,
            timeout=10
        )

        if restart_result.returncode == 0:
            return jsonify({
                'success': True,
                'full_y': full_y,
                'empty_y': empty_y,
                'message': 'Calibration saved and feed-monitor restarted'
            })
        else:
            return jsonify({
                'success': True,
                'full_y': full_y,
                'empty_y': empty_y,
                'warning': 'Calibration saved but service restart failed. Manual restart may be needed.'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/feed/save-training-sample', methods=['POST'])
def save_training_sample():
    """
    Save a marked training sample for ML model training.

    Expects JSON: { "y_position": int, "percent_full": float }

    This saves the current ROI image and the label (Y position + percentage)
    to the training dataset directory.
    """
    try:
        data = request.get_json()
        y_position = int(data.get('y_position', 0))
        percent_full = float(data.get('percent_full', 0))

        # Import feed_config
        import sys
        sys.path.insert(0, '/opt/beeperKeeper')
        from feed_config import IMAGE_PATH, ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT

        # Load the current feed image (should already exist from ROI extraction)
        if not os.path.exists(IMAGE_PATH):
            return jsonify({'success': False, 'error': 'No image available'}), 400

        image = cv2.imread(IMAGE_PATH)
        if image is None:
            return jsonify({'success': False, 'error': 'Could not load image'}), 500

        # Extract ROI
        roi = image[ROI_Y:ROI_Y+ROI_HEIGHT, ROI_X:ROI_X+ROI_WIDTH]

        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        image_filename = f'feed_{timestamp}.jpg'
        label_filename = f'feed_{timestamp}.json'

        # Save ROI image
        image_path = os.path.join(TRAINING_IMAGES_DIR, image_filename)
        cv2.imwrite(image_path, roi, [cv2.IMWRITE_JPEG_QUALITY, 95])

        # Save label
        label_data = {
            'image_filename': image_filename,
            'y_position': y_position,
            'percent_full': round(percent_full, 1),
            'timestamp': datetime.now().isoformat(),
            'roi_coords': {
                'x': ROI_X,
                'y': ROI_Y,
                'width': ROI_WIDTH,
                'height': ROI_HEIGHT
            }
        }

        label_path = os.path.join(TRAINING_LABELS_DIR, label_filename)
        with open(label_path, 'w') as f:
            json.dump(label_data, f, indent=2)

        # Update dataset CSV
        dataset_csv = os.path.join(TRAINING_DATA_DIR, 'dataset.csv')
        csv_exists = os.path.exists(dataset_csv)

        with open(dataset_csv, 'a') as f:
            if not csv_exists:
                f.write('image_path,y_position,percent_full,timestamp\n')

            f.write(f'{image_path},{y_position},{percent_full},{datetime.now().isoformat()}\n')

        # Count total samples
        samples_collected = len([f for f in os.listdir(TRAINING_LABELS_DIR) if f.endswith('.json')])

        return jsonify({
            'success': True,
            'samples_collected': samples_collected,
            'image_saved': image_filename
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/feed/training-progress')
def get_training_progress():
    """Get ML training dataset collection progress"""
    try:
        # Count JSON files in labels directory
        label_files = [f for f in os.listdir(TRAINING_LABELS_DIR) if f.endswith('.json')]
        samples_collected = len(label_files)

        # Calculate distribution by fill level
        distribution = {
            '0-25%': 0,
            '26-50%': 0,
            '51-75%': 0,
            '76-100%': 0
        }

        for label_file in label_files:
            label_path = os.path.join(TRAINING_LABELS_DIR, label_file)
            with open(label_path, 'r') as f:
                label_data = json.load(f)
                percent = label_data.get('percent_full', 0)

                if percent <= 25:
                    distribution['0-25%'] += 1
                elif percent <= 50:
                    distribution['26-50%'] += 1
                elif percent <= 75:
                    distribution['51-75%'] += 1
                else:
                    distribution['76-100%'] += 1

        return jsonify({
            'samples_collected': samples_collected,
            'target': 150,
            'progress_percentage': round((samples_collected / 150) * 100, 1),
            'distribution': distribution
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/feed/full-frame')
def get_feed_full_frame():
    """
    Capture and return full 1920x1080 camera frame for ROI adjustment.

    Temporarily stops MediaMTX to capture a fresh image, then returns
    the full frame as JPEG for the ROI Setup interface.
    """
    try:
        import sys
        from io import BytesIO
        from PIL import Image

        sys.path.insert(0, '/opt/beeperKeeper')
        from feed_config import IMAGE_PATH

        # Trigger fresh image capture (same pattern as ROI capture)
        capture_script = '/opt/beeperKeeper/capture_feed_still.sh'

        result = subprocess.run(
            [capture_script],
            capture_output=True,
            text=True,
            timeout=20
        )

        if result.returncode != 0:
            print(f"✗ Full frame capture failed: {result.stderr}")
            return jsonify({'error': 'Image capture failed'}), 500

        # Load the captured full frame
        if not os.path.exists(IMAGE_PATH):
            print(f"✗ Image file not found: {IMAGE_PATH}")
            return jsonify({'error': 'Image file not found'}), 500

        image = cv2.imread(IMAGE_PATH)
        if image is None:
            print(f"✗ Could not load image from {IMAGE_PATH}")
            return jsonify({'error': 'Could not load image'}), 500

        # Convert BGR (OpenCV) to RGB (PIL)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Convert to PIL Image
        pil_image = Image.fromarray(image_rgb)

        # Save to BytesIO buffer as JPEG
        buffer = BytesIO()
        pil_image.save(buffer, format='JPEG', quality=95)
        full_frame_jpeg = buffer.getvalue()

        print(f"✓ Full frame captured ({len(full_frame_jpeg)} bytes, {image.shape[1]}x{image.shape[0]})")
        return Response(full_frame_jpeg, mimetype='image/jpeg')

    except subprocess.TimeoutExpired:
        print("✗ Full frame capture timeout (>20s)")
        return jsonify({'error': 'Image capture timeout'}), 500
    except Exception as e:
        print(f"✗ Full frame capture error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/feed/save-roi', methods=['POST'])
def save_roi_config():
    """
    Save new ROI coordinates to feed_config.py.

    Expects JSON: { "x": int, "y": int, "width": int, "height": int }

    CRITICAL: ROI changes INVALIDATE all training data and models.
    This endpoint will:
    1. Delete all training images (incompatible ROI coordinates)
    2. Delete trained ML model (incompatible with new ROI)
    3. Reset calibration markers to safe defaults
    4. Update feed_config.py with new ROI
    5. Restart feed-monitor service
    """
    try:
        import re
        import shutil

        # Get and log raw JSON
        data = request.get_json()
        print(f"🔧 ROI Save Request - Raw JSON: {data}")

        # Parse coordinates
        roi_x = int(data.get('x', 0))
        roi_y = int(data.get('y', 0))
        roi_width = int(data.get('width', 0))
        roi_height = int(data.get('height', 0))

        print(f"🔧 ROI Save - Parsed coords: X={roi_x}, Y={roi_y}, W={roi_width}, H={roi_height}")

        # First validation check - log if it fails
        if roi_x < 0 or roi_y < 0 or roi_width < 10 or roi_height < 10:
            error_msg = f"Invalid ROI coordinates - X={roi_x}, Y={roi_y}, W={roi_width}, H={roi_height} (must be positive with minimum 10x10 size)"
            print(f"❌ ROI Save FAILED - {error_msg}")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 400

        # Second validation check - log if it fails
        if roi_x + roi_width > 1920 or roi_y + roi_height > 1080:
            error_msg = f"ROI exceeds frame bounds (1920x1080) - X+W={roi_x}+{roi_width}={roi_x+roi_width}, Y+H={roi_y}+{roi_height}={roi_y+roi_height}"
            print(f"❌ ROI Save FAILED - {error_msg}")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 400

        # =====================================================================
        # DATASET INVALIDATION: Delete training data and models
        # =====================================================================
        cleanup_actions = []

        # 1. Delete training images (all tagged with old ROI coordinates)
        images_deleted = 0
        labels_deleted = 0

        if os.path.exists(TRAINING_IMAGES_DIR):
            images_deleted = len([f for f in os.listdir(TRAINING_IMAGES_DIR) if f.endswith('.jpg')])
            shutil.rmtree(TRAINING_IMAGES_DIR)
            os.makedirs(TRAINING_IMAGES_DIR, exist_ok=True)
            cleanup_actions.append(f"Deleted {images_deleted} training images")
            print(f"🗑️ Deleted {images_deleted} training images from {TRAINING_IMAGES_DIR}")

        if os.path.exists(TRAINING_LABELS_DIR):
            labels_deleted = len([f for f in os.listdir(TRAINING_LABELS_DIR) if f.endswith('.json')])
            shutil.rmtree(TRAINING_LABELS_DIR)
            os.makedirs(TRAINING_LABELS_DIR, exist_ok=True)
            cleanup_actions.append(f"Deleted {labels_deleted} training labels")
            print(f"🗑️ Deleted {labels_deleted} training labels from {TRAINING_LABELS_DIR}")

        # Delete dataset.csv
        dataset_csv_path = os.path.join(TRAINING_DATA_DIR, 'dataset.csv')
        if os.path.exists(dataset_csv_path):
            os.remove(dataset_csv_path)
            cleanup_actions.append("Deleted dataset.csv")
            print(f"🗑️ Deleted dataset.csv")

        # 2. Delete trained ML model (incompatible with new ROI)
        model_path = '/opt/beeperKeeper/models/feed_model.tflite'
        if os.path.exists(model_path):
            os.remove(model_path)
            cleanup_actions.append("Deleted trained ML model")
            print(f"🗑️ Deleted trained model: {model_path}")

        # 3. Delete model metadata if exists
        model_metadata_path = '/opt/beeperKeeper/models/model_metadata.json'
        if os.path.exists(model_metadata_path):
            os.remove(model_metadata_path)
            cleanup_actions.append("Deleted model metadata")
            print(f"🗑️ Deleted model metadata")

        # =====================================================================
        # UPDATE CONFIGURATION
        # =====================================================================

        # Read current feed_config.py
        config_path = '/opt/beeperKeeper/feed_config.py'
        with open(config_path, 'r') as f:
            config_content = f.read()

        # Update ROI coordinates
        config_content = re.sub(
            r'ROI_X\s*=\s*\d+',
            f'ROI_X = {roi_x}',
            config_content
        )
        config_content = re.sub(
            r'ROI_Y\s*=\s*\d+',
            f'ROI_Y = {roi_y}',
            config_content
        )
        config_content = re.sub(
            r'ROI_WIDTH\s*=\s*\d+',
            f'ROI_WIDTH = {roi_width}',
            config_content
        )
        config_content = re.sub(
            r'ROI_HEIGHT\s*=\s*\d+',
            f'ROI_HEIGHT = {roi_height}',
            config_content
        )

        # Reset calibration markers to safe defaults (10% and 90% of ROI height)
        # This prevents out-of-bounds errors until user recalibrates
        safe_full_y = int(roi_height * 0.1)
        safe_empty_y = int(roi_height * 0.9)

        config_content = re.sub(
            r'FEED_LEVEL_FULL_Y\s*=\s*\d+',
            f'FEED_LEVEL_FULL_Y = {safe_full_y}',
            config_content
        )
        config_content = re.sub(
            r'FEED_LEVEL_EMPTY_Y\s*=\s*\d+',
            f'FEED_LEVEL_EMPTY_Y = {safe_empty_y}',
            config_content
        )
        cleanup_actions.append(f"Reset calibration markers to FULL_Y={safe_full_y}, EMPTY_Y={safe_empty_y}")
        print(f"🔧 Reset calibration: FULL_Y={safe_full_y}, EMPTY_Y={safe_empty_y}")

        # Update calibration date and version
        today = datetime.now().strftime('%Y-%m-%d')
        config_content = re.sub(
            r"CALIBRATION_DATE\s*=\s*['\"].*?['\"]",
            f"CALIBRATION_DATE = '{today}'",
            config_content
        )

        # Write updated config
        with open(config_path, 'w') as f:
            f.write(config_content)

        # Clear ROI image cache (force fresh capture with new ROI)
        with roi_image_cache['lock']:
            roi_image_cache['image_data'] = None
            roi_image_cache['timestamp'] = 0

        # Restart feed-monitor service to apply new ROI
        restart_result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'feed-monitor'],
            capture_output=True,
            timeout=10
        )

        if restart_result.returncode == 0:
            print(f"✅ ROI Save SUCCESS - Updated config: X={roi_x}, Y={roi_y}, W={roi_width}, H={roi_height}")
            return jsonify({
                'success': True,
                'roi': {
                    'x': roi_x,
                    'y': roi_y,
                    'width': roi_width,
                    'height': roi_height
                },
                'cleanup_actions': cleanup_actions,
                'training_data_deleted': {
                    'images': images_deleted,
                    'labels': labels_deleted
                },
                'calibration_reset': {
                    'full_y': safe_full_y,
                    'empty_y': safe_empty_y
                },
                'message': f'ROI updated successfully. Training data cleared - recalibration required.',
                'warning': '⚠️ All training data and ML model deleted due to ROI change. You must recalibrate and retrain.'
            })
        else:
            print(f"⚠️ ROI Save SUCCESS (with warning) - Updated config: X={roi_x}, Y={roi_y}, W={roi_width}, H={roi_height}, service restart failed")
            return jsonify({
                'success': True,
                'roi': {
                    'x': roi_x,
                    'y': roi_y,
                    'width': roi_width,
                    'height': roi_height
                },
                'cleanup_actions': cleanup_actions,
                'training_data_deleted': {
                    'images': images_deleted,
                    'labels': labels_deleted
                },
                'calibration_reset': {
                    'full_y': safe_full_y,
                    'empty_y': safe_empty_y
                },
                'warning': 'ROI saved and dataset cleared, but service restart failed. Manual restart may be needed.'
            })

    except Exception as e:
        error_msg = f"Exception in save_roi_config: {str(e)}"
        print(f"❌ ROI Save EXCEPTION - {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500

@app.route('/api/feed/ml-predict')
def ml_predict_feed_level():
    """
    Run ML inference on current ROI image to predict feed level.

    Uses the trained TensorFlow Lite CNN model to predict feed level percentage
    from the current camera ROI image.

    Returns JSON with prediction, confidence, inference time, and detected Y position.
    """
    try:
        import numpy as np
        from PIL import Image
        import sys

        # Model path
        MODEL_PATH = '/opt/beeperKeeper/models/feed_model.tflite'

        # Check if model exists
        if not os.path.exists(MODEL_PATH):
            return jsonify({
                'success': False,
                'error': 'Model not found - training may still be in progress. Check /opt/beeperKeeper/models/feed_model.tflite'
            }), 404

        # Import TensorFlow Lite
        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            try:
                import tensorflow.lite as tflite
            except ImportError:
                return jsonify({
                    'success': False,
                    'error': 'TensorFlow Lite not installed. Run: pip3 install tflite-runtime'
                }), 500

        # Load feed config for ROI extraction
        sys.path.insert(0, '/opt/beeperKeeper')
        from feed_config import IMAGE_PATH, ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT, FEED_LEVEL_FULL_Y, FEED_LEVEL_EMPTY_Y

        # Capture fresh ROI image (reuse existing capture logic)
        capture_script = '/opt/beeperKeeper/capture_feed_still.sh'
        result = subprocess.run(
            [capture_script],
            capture_output=True,
            text=True,
            timeout=20
        )

        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'Image capture failed: {result.stderr}'
            }), 500

        # Load captured image
        if not os.path.exists(IMAGE_PATH):
            return jsonify({
                'success': False,
                'error': f'Captured image not found: {IMAGE_PATH}'
            }), 500

        full_image = cv2.imread(IMAGE_PATH)
        if full_image is None:
            return jsonify({
                'success': False,
                'error': 'Could not load captured image'
            }), 500

        # Extract ROI
        roi = full_image[ROI_Y:ROI_Y+ROI_HEIGHT, ROI_X:ROI_X+ROI_WIDTH]

        # Convert BGR to RGB
        roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)

        # Resize to model input size (224x224) - MobileNetV2 standard
        roi_resized = cv2.resize(roi_rgb, (224, 224))

        # Normalize to 0-1 range (float32)
        roi_normalized = roi_resized.astype(np.float32) / 255.0

        # Add batch dimension: (1, 224, 224, 3)
        input_data = np.expand_dims(roi_normalized, axis=0)

        # Load TFLite model
        start_time = time.time()
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()

        # Get input/output tensor details
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()

        # Set input tensor
        interpreter.set_tensor(input_details[0]['index'], input_data)

        # Run inference
        interpreter.invoke()

        # Get output (feed level percentage 0-100)
        output = interpreter.get_tensor(output_details[0]['index'])
        prediction_percent = float(output[0][0])  # Convert from numpy.float32 to Python float

        inference_time_ms = (time.time() - start_time) * 1000

        # Calculate detected Y position from prediction percentage
        # prediction_percent: 100% = FULL_Y, 0% = EMPTY_Y
        y_range = FEED_LEVEL_EMPTY_Y - FEED_LEVEL_FULL_Y
        detected_y = int(FEED_LEVEL_FULL_Y + (y_range * (100 - prediction_percent) / 100))

        # Calculate confidence (use absolute prediction value as confidence)
        # For regression models, confidence is harder to derive - use a simple heuristic
        # If prediction is close to extremes (0 or 100), higher confidence
        # If prediction is in middle range, lower confidence (more ambiguous)
        confidence_raw = 100 - abs(50 - prediction_percent) * 0.8  # Scale: 60-100%
        confidence = float(max(60, min(100, confidence_raw)))

        return jsonify({
            'success': True,
            'prediction': round(float(prediction_percent), 1),
            'confidence': round(confidence, 1),
            'inference_time_ms': round(inference_time_ms, 1),
            'detected_y': detected_y,
            'model_type': 'TensorFlow Lite CNN',
            'training_samples': 292,
            'timestamp': datetime.now().isoformat()
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Image capture timeout (>20s)'
        }), 500
    except Exception as e:
        print(f"ML prediction error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Prediction failed: {str(e)}'
        }), 500

@app.route("/health")
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check audio device
        result = subprocess.run([
            "aplay", "-l"
        ], capture_output=True, timeout=5)
        
        audio_ok = b"E4K" in result.stdout
        
        # Check MQTT connection
        mqtt_ok = mqtt_client and mqtt_client.is_connected()
        
        # Check service status
        health_status = {
            "status": "healthy" if audio_ok and mqtt_ok else "degraded",
            "audio_device": "ok" if audio_ok else "error",
            "mqtt": "connected" if mqtt_ok else "disconnected",
            "uptime": int((time.time() - START_TIME))
        }
        
        status_code = 200 if (audio_ok and mqtt_ok) else 503
        return jsonify(health_status), status_code
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🐔 BEEPER KEEPER v2.0 - HLS Streaming Edition")
    print("="*60)

    # Initialize MQTT
    print("\n📡 Connecting to MQTT broker...")
    init_mqtt()

    # Give MQTT a moment to connect
    time.sleep(2)

    # Initialize email alert scheduler
    if SMTP_ENABLED:
        print("\n📧 Initializing email alert scheduler...")
        scheduler = BackgroundScheduler(timezone=pytz.timezone('America/New_York'))

        # Schedule lights ON alert (6:15 AM - 15 minutes before 6:30 AM)
        scheduler.add_job(
            func=lambda: send_scheduled_alerts('lights_on'),
            trigger=CronTrigger(hour=6, minute=15),
            id='lights_on_alert',
            name='Lights ON Alert (15 min before)',
            replace_existing=True
        )

        # Schedule lights OFF alert (6:45 PM - 15 minutes before 7:00 PM)
        scheduler.add_job(
            func=lambda: send_scheduled_alerts('lights_off'),
            trigger=CronTrigger(hour=18, minute=45),
            id='lights_off_alert',
            name='Lights OFF Alert (15 min before)',
            replace_existing=True
        )

        scheduler.start()
        print("✓ Alert scheduler started (6:15 AM and 6:45 PM daily)")
        print(f"✓ SMTP configured: {SMTP_HOST}")
    else:
        print("\n⚠ Email alerts disabled - SMTP not configured")
        print("  Set GF_SMTP_ENABLED=true in environment to enable")

    print("\n✓ Starting web server on http://0.0.0.0:8080")
    print(f"✓ HLS streams available via Flask proxy routes")
    print(f"✓ WebSocket streaming enabled on /announce_stream namespace")
    print("\nPress Ctrl+C to stop\n")

    try:
        socketio.run(app, host='0.0.0.0', port=8080, debug=False)
    except (KeyboardInterrupt, SystemExit):
        if SMTP_ENABLED:
            scheduler.shutdown()
            print("\n✓ Scheduler stopped")
