"""
BeeperKeeper Flask Application Factory

Creates and configures the Flask application.
"""
import time
from flask import Flask
from .config import get_config
from .extensions import socketio, limiter


def create_app(config_class=None):
    """
    Application factory for BeeperKeeper Flask app.

    Args:
        config_class: Configuration class to use. Defaults to production.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    # Load configuration
    if config_class is None:
        config_class = get_config()
    app.config.from_object(config_class)

    # Store start time for health checks
    app.config['START_TIME'] = time.time()

    # Initialize extensions
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet')
    limiter.init_app(app)

    # Initialize services
    _init_services(app)

    # Register blueprints
    _register_blueprints(app)

    # Register WebSocket handlers
    _register_websocket_handlers(app)

    # Initialize MQTT
    _init_mqtt(app)

    # Initialize scheduler
    _init_scheduler(app)

    return app


def _init_services(app):
    """Initialize service instances and attach to app config"""
    from .services.alert_service import AlertService
    from .services.feed_service import FeedService

    # Create service instances with app config
    app.config['alert_service'] = AlertService(app.config)
    app.config['feed_service'] = FeedService(app.config)


def _register_blueprints(app):
    """Register all route blueprints"""
    from .routes import main_bp, api_bp, feed_bp, stream_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(stream_bp)


def _register_websocket_handlers(app):
    """Register SocketIO event handlers"""
    from flask_socketio import emit, disconnect
    import threading
    import subprocess
    import tempfile
    import os

    # Streaming sessions tracking
    streaming_sessions = {}
    streaming_sessions_lock = threading.Lock()

    @socketio.on('connect', namespace='/announce_stream')
    def handle_stream_connect():
        from flask import request
        session_id = request.sid
        print(f"Stream client connected: {session_id}")

    @socketio.on('start_stream', namespace='/announce_stream')
    def handle_start_stream(data=None):
        from flask import request
        session_id = request.sid

        with streaming_sessions_lock:
            streaming_sessions[session_id] = {
                'chunks': [],
                'started': time.time(),
                'username': data.get('username', 'Anonymous') if data else 'Anonymous'
            }

        emit('stream_started', {'session_id': session_id})

    @socketio.on('audio_chunk', namespace='/announce_stream')
    def handle_audio_chunk(data):
        from flask import request
        session_id = request.sid

        with streaming_sessions_lock:
            if session_id in streaming_sessions:
                streaming_sessions[session_id]['chunks'].append(data['chunk'])

    @socketio.on('stop_stream', namespace='/announce_stream')
    def handle_stop_stream():
        from flask import request
        session_id = request.sid
        _cleanup_stream(session_id, streaming_sessions, streaming_sessions_lock)

    @socketio.on('disconnect', namespace='/announce_stream')
    def handle_stream_disconnect():
        from flask import request
        _cleanup_stream(request.sid, streaming_sessions, streaming_sessions_lock)


def _cleanup_stream(session_id, sessions, lock):
    """Process and cleanup a streaming session"""
    import subprocess
    import tempfile
    import os
    import base64
    from flask_socketio import emit

    with lock:
        if session_id not in sessions:
            return

        session = sessions.pop(session_id)
        chunks = session.get('chunks', [])
        username = session.get('username', 'Anonymous')

    if not chunks:
        return

    try:
        # Combine chunks
        audio_data = b''.join(base64.b64decode(chunk) for chunk in chunks)

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
            f.write(audio_data)
            temp_path = f.name

        # Convert and play
        output_path = temp_path.replace('.webm', '.wav')
        subprocess.run([
            'ffmpeg', '-y', '-i', temp_path,
            '-acodec', 'pcm_s16le', '-ar', '48000', '-ac', '1',
            output_path
        ], capture_output=True, timeout=10)

        if os.path.exists(output_path):
            subprocess.run(['aplay', '-D', 'plughw:E4K,0', output_path],
                           capture_output=True, timeout=30)

        # Cleanup
        for path in [temp_path, output_path]:
            if os.path.exists(path):
                os.remove(path)

        print(f"Played announcement from {username}")

    except Exception as e:
        print(f"Stream playback error: {e}")


def _init_mqtt(app):
    """Initialize MQTT connection"""
    from .services.mqtt_service import mqtt_service

    mqtt_service.broker = app.config.get('MQTT_BROKER', '10.10.10.7')
    mqtt_service.port = app.config.get('MQTT_PORT', 1883)
    mqtt_service.connect()


def _init_scheduler(app):
    """Initialize background scheduler for alerts"""
    if not app.config.get('SMTP_ENABLED', False):
        print("SMTP disabled - alert scheduler not started")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz

        alert_service = app.config.get('alert_service')
        if not alert_service:
            return

        scheduler = BackgroundScheduler(timezone=pytz.timezone('America/New_York'))

        # Lights ON alert (6:15 AM - 15 min before)
        scheduler.add_job(
            func=lambda: alert_service.send_scheduled_alerts('lights_on'),
            trigger=CronTrigger(hour=6, minute=15),
            id='lights_on_alert',
            name='Lights ON Alert',
            replace_existing=True
        )

        # Lights OFF alert (6:45 PM - 15 min before)
        scheduler.add_job(
            func=lambda: alert_service.send_scheduled_alerts('lights_off'),
            trigger=CronTrigger(hour=18, minute=45),
            id='lights_off_alert',
            name='Lights OFF Alert',
            replace_existing=True
        )

        scheduler.start()
        app.config['scheduler'] = scheduler
        print("Alert scheduler started (6:15 AM and 6:45 PM daily)")

    except Exception as e:
        print(f"Scheduler initialization error: {e}")
