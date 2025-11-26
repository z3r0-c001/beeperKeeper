"""
User Service

Manages active users and chat functionality.
"""
import time
import threading
from collections import deque

# Active users tracking (ephemeral, in-memory)
# Format: { 'username': {'last_seen': timestamp, 'state': 'viewing'|'away', 'first_seen': timestamp} }
active_users = {}
active_users_lock = threading.Lock()

# Chat messages (ephemeral, last 50)
chat_messages = deque(maxlen=50)
chat_lock = threading.Lock()

MAX_CHAT_MESSAGES = 50
USER_TIMEOUT = 120  # seconds before user considered stale


class UserService:
    """User and chat management"""

    @staticmethod
    def update_activity(username, state='viewing'):
        """Update user's activity timestamp"""
        if not username:
            return

        with active_users_lock:
            current_time = time.time()
            if username in active_users:
                active_users[username]['last_seen'] = current_time
                active_users[username]['state'] = state
            else:
                active_users[username] = {
                    'last_seen': current_time,
                    'first_seen': current_time,
                    'state': state
                }

    @staticmethod
    def remove_user(username):
        """Remove user from active users"""
        with active_users_lock:
            if username in active_users:
                del active_users[username]

    @staticmethod
    def cleanup_stale():
        """Remove users not seen in the last 2 minutes"""
        with active_users_lock:
            current_time = time.time()
            stale_users = [
                username for username, data in active_users.items()
                if current_time - data['last_seen'] > USER_TIMEOUT
            ]
            for username in stale_users:
                del active_users[username]

    @staticmethod
    def get_active_list():
        """Get list of active users with their status"""
        UserService.cleanup_stale()

        with active_users_lock:
            current_time = time.time()
            users_list = []

            for username, data in active_users.items():
                last_seen = data['last_seen']
                time_since = current_time - last_seen

                # Determine current state
                if time_since < 30:
                    status = 'active'
                elif time_since < 60:
                    status = 'idle'
                else:
                    status = 'away'

                users_list.append({
                    'username': username,
                    'status': status,
                    'state': data.get('state', 'viewing'),
                    'last_seen_seconds': int(time_since)
                })

            # Sort by most recently active
            users_list.sort(key=lambda x: x['last_seen_seconds'])
            return users_list

    @staticmethod
    def add_chat_message(username, message, message_type='chat'):
        """Add a chat message"""
        with chat_lock:
            chat_messages.append({
                'username': username,
                'message': message,
                'type': message_type,
                'timestamp': time.time()
            })

    @staticmethod
    def get_chat_messages():
        """Get recent chat messages"""
        with chat_lock:
            return list(chat_messages)
