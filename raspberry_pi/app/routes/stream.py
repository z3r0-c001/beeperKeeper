"""
Stream Routes Blueprint

Camera stream proxies and Grafana proxy.
"""
from flask import Blueprint, Response, request, jsonify
import requests

stream_bp = Blueprint('stream', __name__)


@stream_bp.route('/csi_camera/<path:subpath>')
def proxy_csi_camera(subpath):
    """Proxy HLS stream from local MediaMTX for CSI camera"""
    try:
        mediamtx_url = f"http://localhost:8888/csi_camera/{subpath}"

        resp = requests.get(
            mediamtx_url,
            params=request.args,
            stream=True,
            timeout=10
        )

        # Determine content type
        if subpath.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif subpath.endswith('.ts'):
            content_type = 'video/mp2t'
        else:
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')

        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(generate(), status=resp.status_code)
        response.headers['Content-Type'] = content_type
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Access-Control-Allow-Origin'] = '*'

        return response

    except requests.exceptions.RequestException as e:
        return jsonify({'error': 'Stream unavailable'}), 502


@stream_bp.route('/usb_camera/<path:subpath>')
def proxy_usb_camera(subpath):
    """Proxy HLS stream from local MediaMTX for USB camera"""
    try:
        mediamtx_url = f"http://localhost:8888/usb_camera/{subpath}"

        resp = requests.get(
            mediamtx_url,
            params=request.args,
            stream=True,
            timeout=10
        )

        # Determine content type
        if subpath.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif subpath.endswith('.ts'):
            content_type = 'video/mp2t'
        else:
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')

        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(generate(), status=resp.status_code)
        response.headers['Content-Type'] = content_type
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Access-Control-Allow-Origin'] = '*'

        return response

    except requests.exceptions.RequestException as e:
        return jsonify({'error': 'Stream unavailable'}), 502


@stream_bp.route('/grafana/<path:subpath>')
def proxy_grafana(subpath):
    """Proxy Grafana dashboard to avoid CORS/iframe issues"""
    try:
        grafana_url = f"http://10.10.10.7:3000/{subpath}"

        resp = requests.get(
            grafana_url,
            params=request.args,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            stream=True,
            timeout=30
        )

        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(generate(), status=resp.status_code)

        # Copy relevant headers
        for key, value in resp.headers.items():
            if key.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                response.headers[key] = value

        # Allow iframe embedding
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"

        return response

    except Exception as e:
        return jsonify({'error': 'Grafana unavailable'}), 502
