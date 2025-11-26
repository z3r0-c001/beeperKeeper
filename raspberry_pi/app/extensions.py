"""
Flask Extensions

Initialize extensions here without app context.
Extensions are bound to app in create_app().
"""
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# SocketIO for real-time communication
socketio = SocketIO()

# Rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["10000 per day", "3000 per hour"],
    storage_uri="memory://"
)
