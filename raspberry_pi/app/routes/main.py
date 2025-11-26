"""
Main Routes Blueprint

Index page and static content routes.
"""
from flask import Blueprint, render_template, send_from_directory, request

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Serve the main dashboard"""
    return render_template('index.html')


@main_bp.route('/chicken_image')
def chicken_image():
    """Serve chicken logo"""
    return send_from_directory('static/images', 'chicken_of_despair.png')


@main_bp.route('/usb_test')
def usb_test():
    """USB camera test page"""
    return send_from_directory('static', 'usb_test.html')


@main_bp.route('/csi_test')
def csi_test():
    """CSI camera test page"""
    return send_from_directory('static', 'csi_test.html')


@main_bp.route('/train-feed')
def train_feed():
    """Serve the feed training interface"""
    return render_template('train_feed.html')


@main_bp.route('/unsubscribe')
def unsubscribe_page():
    """Handle unsubscribe page - returns styled HTML"""
    from flask import current_app
    token = request.args.get('token')

    if not token:
        return """<!DOCTYPE html>
<html><head><title>Invalid Request</title>
<style>
    body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; }
    .container { background: #16213e; padding: 40px; border-radius: 12px;
                 max-width: 500px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);
                 border: 2px solid #14b8a6; text-align: center; }
    h1 { font-size: 2rem; margin-bottom: 20px; color: #60a5fa; }
    p { font-size: 1.1rem; line-height: 1.6; }
</style>
</head>
<body>
    <div class="container">
        <h1>Beeper Keeper</h1>
        <h2>Invalid Request</h2>
        <p>Please use the unsubscribe link provided in your alert emails.</p>
    </div>
</body>
</html>""", 400

    # Token provided - show unsubscribe confirmation
    # (Actual unsubscription handled by API endpoint)
    return render_template('unsubscribe.html', token=token)


@main_bp.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    import subprocess
    import time
    from flask import jsonify, current_app

    try:
        # Check audio device
        result = subprocess.run(['aplay', '-l'], capture_output=True, timeout=5)
        audio_ok = b'E4K' in result.stdout

        # Check MQTT connection
        from app.services import mqtt_service
        mqtt_ok = mqtt_service.mqtt_service.is_connected()

        status = 'healthy' if audio_ok and mqtt_ok else 'degraded'
        status_code = 200 if (audio_ok and mqtt_ok) else 503

        return jsonify({
            'status': status,
            'audio_device': 'ok' if audio_ok else 'error',
            'mqtt': 'connected' if mqtt_ok else 'disconnected',
            'uptime': int(time.time() - current_app.config.get('START_TIME', time.time()))
        }), status_code

    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500
