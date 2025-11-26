"""
API Routes Blueprint

REST API endpoints for metrics, users, chat, and alerts.
"""
from flask import Blueprint, jsonify, request, Response
from app.extensions import limiter
from app.services.mqtt_service import sensor_data
from app.services.user_service import UserService
from app.utils.auth import get_username_from_jwt, get_authenticated_username, require_local_network_email
from app.utils.helpers import get_cpu_temp, get_system_stats, format_bme680_data, format_camera_metadata
import time
import queue
import threading
import subprocess
import tempfile

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Audio announcement queue
announcement_queue = queue.Queue(maxsize=5)
announcement_lock = threading.Lock()


@api_bp.route('/metrics')
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


@api_bp.route('/heartbeat', methods=['POST'])
@limiter.limit("60 per minute")
def api_heartbeat():
    """Heartbeat endpoint for active user tracking"""
    username = get_authenticated_username()
    state = request.json.get('state', 'viewing') if request.is_json else 'viewing'

    UserService.update_activity(username, state)

    return jsonify({
        'status': 'ok',
        'username': username,
        'server_time': int(time.time())
    })


@api_bp.route('/user_left', methods=['POST'])
@limiter.limit("30 per minute")
def api_user_left():
    """Handle user leaving the page"""
    username = get_authenticated_username()
    UserService.remove_user(username)
    return jsonify({'status': 'ok'})


@api_bp.route('/active_users')
def api_active_users():
    """Get list of active users"""
    return jsonify({
        'users': UserService.get_active_list(),
        'count': len(UserService.get_active_list())
    })


@api_bp.route('/chat/send', methods=['POST'])
@limiter.limit("30 per minute")
def api_chat_send():
    """Send a chat message"""
    if not request.is_json:
        return jsonify({'error': 'JSON required'}), 400

    username = get_authenticated_username()
    message = request.json.get('message', '').strip()

    if not message:
        return jsonify({'error': 'Message required'}), 400

    if len(message) > 500:
        return jsonify({'error': 'Message too long (max 500 chars)'}), 400

    # Sanitize message
    from markupsafe import escape
    message = str(escape(message))

    UserService.add_chat_message(username, message)

    return jsonify({
        'status': 'ok',
        'username': username,
        'message': message
    })


@api_bp.route('/chat/messages')
def api_chat_messages():
    """Get recent chat messages"""
    return jsonify({
        'messages': UserService.get_chat_messages()
    })


@api_bp.route('/lights_countdown')
@limiter.limit("60 per minute")
def lights_countdown():
    """Get countdown to next light state change"""
    from flask import current_app
    alert_service = current_app.config.get('alert_service')
    if alert_service:
        return jsonify(alert_service.get_lights_countdown())
    return jsonify({'error': 'Alert service not available'}), 503


@api_bp.route('/lights/alerts/subscribe', methods=['POST'])
@limiter.limit("10 per minute")
def api_subscribe_alerts():
    """Subscribe to light alerts"""
    from flask import current_app
    alert_service = current_app.config.get('alert_service')

    if not alert_service:
        return jsonify({'error': 'Alert service not available'}), 503

    if not request.is_json:
        return jsonify({'error': 'JSON required'}), 400

    email = request.json.get('email', '').strip().lower()
    alert_on = request.json.get('alert_on', True)
    alert_off = request.json.get('alert_off', True)

    if not email or not alert_service.validate_email(email):
        return jsonify({'error': 'Valid email required'}), 400

    # Load and update subscriptions
    subs = alert_service.load_subscriptions()
    subs[email] = {
        'alert_on': alert_on,
        'alert_off': alert_off,
        'subscribed_at': time.time()
    }
    alert_service.save_subscriptions(subs)

    # Send confirmation email
    alert_service.send_light_alert(email, 'subscription', alert_on, alert_off)

    return jsonify({
        'status': 'subscribed',
        'email': email,
        'alert_on': alert_on,
        'alert_off': alert_off
    })


@api_bp.route('/lights/alerts/unsubscribe', methods=['POST'])
@limiter.limit("10 per minute")
def api_unsubscribe_alerts():
    """Unsubscribe from light alerts"""
    from flask import current_app
    alert_service = current_app.config.get('alert_service')

    if not alert_service:
        return jsonify({'error': 'Alert service not available'}), 503

    if not request.is_json:
        return jsonify({'error': 'JSON required'}), 400

    email = request.json.get('email', '').strip().lower()

    if not email:
        return jsonify({'error': 'Email required'}), 400

    subs = alert_service.load_subscriptions()
    if email in subs:
        del subs[email]
        alert_service.save_subscriptions(subs)

    return jsonify({'status': 'unsubscribed', 'email': email})


@api_bp.route('/lights/alerts/check')
def api_check_subscription():
    """Check if email is subscribed"""
    from flask import current_app
    alert_service = current_app.config.get('alert_service')

    if not alert_service:
        return jsonify({'error': 'Alert service not available'}), 503

    email = request.args.get('email', '').strip().lower()
    if not email:
        return jsonify({'subscribed': False})

    subs = alert_service.load_subscriptions()
    if email in subs:
        return jsonify({
            'subscribed': True,
            'alert_on': subs[email].get('alert_on', True),
            'alert_off': subs[email].get('alert_off', True)
        })

    return jsonify({'subscribed': False})


@api_bp.route('/announce', methods=['POST'])
@limiter.limit("10 per minute")
@require_local_network_email
def api_announce():
    """Receive audio announcement from authenticated user"""
    username = get_username_from_jwt()

    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    audio_data = audio_file.read()

    # Validate size
    MAX_SIZE = 1_000_000  # 1MB
    if len(audio_data) > MAX_SIZE:
        return jsonify({'error': 'Audio too long (max 30s / 1MB)'}), 400
    if len(audio_data) < 1000:
        return jsonify({'error': 'Audio too short'}), 400

    try:
        announcement_queue.put_nowait((audio_data, username))
        queue_size = announcement_queue.qsize()

        return jsonify({
            'status': 'queued',
            'message': 'Announcement will play shortly',
            'queue_position': queue_size,
            'username': username
        })
    except queue.Full:
        return jsonify({'error': 'Queue full (max 5), try again later'}), 503
