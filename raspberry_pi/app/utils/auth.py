"""
Authentication Utilities

JWT token handling and authorization helpers.
"""
import jwt
from jwt.exceptions import InvalidTokenError
from flask import request
from functools import wraps


def get_username_from_jwt():
    """
    Extract username from Cloudflare Access JWT token.
    Returns username (email prefix) or None if not authenticated.
    """
    # Check for Cloudflare Access JWT
    cf_jwt = request.headers.get('Cf-Access-Jwt-Assertion')
    if not cf_jwt:
        return None

    try:
        # Decode without verification (Cloudflare handles verification)
        # We just need to extract the email claim
        payload = jwt.decode(cf_jwt, options={"verify_signature": False})
        email = payload.get('email', '')
        if email:
            # Return username (everything before @)
            return email.split('@')[0]
    except (InvalidTokenError, Exception):
        pass

    return None


def get_authenticated_username():
    """
    Get username from JWT or derive from local network access.
    Falls back to IP-based identifier for local access.
    """
    # Try JWT first (Cloudflare Access)
    username = get_username_from_jwt()
    if username:
        return username

    # Fall back to request parameter
    if request.is_json:
        username = request.json.get('username', '')
    else:
        username = request.args.get('username', '')
    if username:
        return username[:50]  # Limit length

    # For local network access, use IP address as identifier
    remote_addr = request.remote_addr or ''
    if remote_addr.startswith('10.10.10.') or remote_addr == '127.0.0.1':
        return remote_addr

    return 'Anonymous'


def require_local_network_email(f):
    """
    Decorator to require @YOUR_DOMAIN email authentication.
    Returns 401 if not authenticated via Cloudflare Access.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        cf_jwt = request.headers.get('Cf-Access-Jwt-Assertion')
        if not cf_jwt:
            from flask import jsonify
            return jsonify({
                'error': 'Authentication required',
                'message': 'This endpoint requires Cloudflare Access authentication'
            }), 401

        try:
            payload = jwt.decode(cf_jwt, options={"verify_signature": False})
            email = payload.get('email', '')

            if not email.endswith('@YOUR_DOMAIN'):
                from flask import jsonify
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Only @YOUR_DOMAIN emails are allowed'
                }), 403

        except (InvalidTokenError, Exception) as e:
            from flask import jsonify
            return jsonify({
                'error': 'Invalid token',
                'message': str(e)
            }), 401

        return f(*args, **kwargs)

    return decorated_function
