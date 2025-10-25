#!/usr/bin/env python3
"""
motionOne Production Camera Server - 24/7 Reliable Monitoring
Features: 720p @ 15fps, production error handling, health monitoring, auto-recovery
"""

from flask import Flask, Response, jsonify, request
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
from libcamera import Transform
import io
import threading
import time
import signal
import sys
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import subprocess
import re
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            '/var/log/camera_server.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
@dataclass
class Config:
    CAMERA_RESOLUTION = (1280, 720)
    CAMERA_FPS = 15
    JPEG_QUALITY = 65
    METADATA_UPDATE_INTERVAL = 0.5  # seconds
    HEALTH_CHECK_INTERVAL = 30  # seconds
    MAX_INIT_RETRIES = 5
    INIT_RETRY_DELAY = 5  # seconds
    WATCHDOG_TIMEOUT = 120  # seconds - if no frames for this long, restart
    MAX_FRAME_AGE = 10  # seconds - if last frame is older, report unhealthy

# Global state
class ServerState:
    def __init__(self):
        self.picam2: Optional[Picamera2] = None
        self.output: Optional['StreamingOutput'] = None
        self.metadata_thread: Optional[threading.Thread] = None
        self.health_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()
        self.camera_ready = False
        self.last_frame_time = 0
        self.last_health_check = time.time()
        self.error_count = 0
        self.current_metadata = {
            "lux": 0,
            "exposure": 0,
            "gain": 0,
            "temperature": 0,
            "timestamp": datetime.now().isoformat(),
            "health": "initializing"
        }
        # In-memory log buffer for web display
        self.log_buffer = deque(maxlen=500)  # Keep last 500 log entries
        self.start_time = time.time()

state = ServerState()

# Custom logging handler to capture logs for web display
class WebLogHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'message': record.getMessage(),
                'module': record.module
            }
            state.log_buffer.append(log_entry)
        except Exception:
            pass

# Add web log handler
web_handler = WebLogHandler()
web_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(web_handler)

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()
        self.frame_count = 0

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.frame_count += 1
            state.last_frame_time = time.time()
            self.condition.notify_all()

def check_camera_hardware():
    """Pre-flight check for camera hardware availability"""
    try:
        # Check if camera device exists
        if not os.path.exists('/dev/video0'):
            logger.error("Camera device /dev/video0 not found")
            return False
        
        # Try to list cameras using picamera2
        cameras = Picamera2.global_camera_info()
        if not cameras:
            logger.error("No cameras detected by libcamera")
            return False
        
        logger.info(f"Camera hardware detected: {cameras}")
        return True
    except Exception as e:
        logger.error(f"Camera hardware check failed: {e}")
        return False

def initialize_camera(max_retries=Config.MAX_INIT_RETRIES):
    """Initialize camera with retries and proper error handling"""
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Camera initialization attempt {attempt}/{max_retries}")
            
            # Pre-check hardware
            if not check_camera_hardware():
                logger.warning(f"Hardware check failed, waiting {Config.INIT_RETRY_DELAY}s...")
                time.sleep(Config.INIT_RETRY_DELAY)
                continue
            
            # Initialize camera
            picam2 = Picamera2()
            transform = Transform(hflip=1, vflip=1)
            
            config = picam2.create_video_configuration(
                main={"size": Config.CAMERA_RESOLUTION, "format": "RGB888"},
                encode="main",
                transform=transform
            )
            
            logger.info("Configuring camera...")
            picam2.configure(config)
            
            # Setup streaming
            output = StreamingOutput()
            encoder = JpegEncoder(q=Config.JPEG_QUALITY)
            
            logger.info("Starting camera recording...")
            picam2.start_recording(encoder, FileOutput(output))
            
            # Wait a bit to ensure camera is actually working
            time.sleep(2)
            
            # Verify we're getting frames
            if output.frame_count == 0:
                logger.error("Camera started but no frames received")
                picam2.stop_recording()
                picam2.close()
                raise RuntimeError("No frames from camera")
            
            logger.info(f"✓ Camera initialized successfully: {Config.CAMERA_RESOLUTION} @ {Config.CAMERA_FPS}fps")
            return picam2, output
            
        except Exception as e:
            logger.error(f"Camera init attempt {attempt} failed: {e}", exc_info=True)
            
            if attempt < max_retries:
                wait_time = Config.INIT_RETRY_DELAY * attempt  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.critical("Max retries exceeded. Cannot initialize camera.")
                return None, None
    
    return None, None

def metadata_update_thread():
    """Background thread to update metadata without blocking video stream"""
    logger.info("Metadata update thread started")
    
    while not state.shutdown_event.is_set():
        try:
            if state.picam2 and state.camera_ready:
                metadata = state.picam2.capture_metadata()
                lux = metadata.get("Lux", 0)
                
                state.current_metadata.update({
                    "lux": lux,
                    "exposure": metadata.get("ExposureTime", 0),
                    "gain": metadata.get("AnalogueGain", 1.0),
                    "temperature": metadata.get("ColourTemperature", 0),
                    "timestamp": datetime.now().isoformat(),
                    "health": "healthy" if state.camera_ready else "degraded"
                })
                
            state.shutdown_event.wait(Config.METADATA_UPDATE_INTERVAL)
            
        except Exception as e:
            logger.error(f"Metadata update error: {e}")
            state.error_count += 1
            time.sleep(1)

def health_check_thread():
    """Monitor camera health and detect stuck streams"""
    logger.info("Health check thread started")
    
    while not state.shutdown_event.is_set():
        try:
            current_time = time.time()
            
            # Check if we're getting frames
            if state.last_frame_time > 0:
                frame_age = current_time - state.last_frame_time
                
                if frame_age > Config.MAX_FRAME_AGE:
                    logger.warning(f"No frames for {frame_age:.1f}s - camera may be stuck")
                    state.current_metadata["health"] = "degraded"
                    
                    if frame_age > Config.WATCHDOG_TIMEOUT:
                        logger.critical(f"Watchdog timeout! No frames for {frame_age:.1f}s")
                        logger.critical("Camera is completely stuck - EXITING for systemd restart")
                        # Exit with error code to trigger systemd restart
                        os._exit(1)
                else:
                    if state.camera_ready:
                        state.current_metadata["health"] = "healthy"
            
            state.last_health_check = current_time
            state.shutdown_event.wait(Config.HEALTH_CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Health check error: {e}")
            time.sleep(5)

def generate_frames(output):
    """Stream frames with timeout protection"""
    logger.info("Frame generator started")
    
    while not state.shutdown_event.is_set():
        try:
            with output.condition:
                # Wait for frame with timeout
                output.condition.wait(timeout=5.0)
                
                if output.frame is None:
                    continue
                
                frame = output.frame
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                   
        except Exception as e:
            logger.error(f"Frame generation error: {e}")
            time.sleep(0.1)

@app.route('/')
def index():
    return """
    <html>
      <head>
        <title>motionOne - Production IR Camera</title>
        <style>
          body { background: #000; margin: 0; font-family: Arial, sans-serif; color: #fff; }
          .container { max-width: 1920px; margin: 0 auto; padding: 20px; }
          h1 { text-align: center; margin-bottom: 20px; }
          .status-banner { 
            background: #1a3a1a; border: 2px solid #4CAF50; 
            padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: center;
          }
          .status-banner.degraded { background: #3a2a1a; border-color: #FFA726; }
          .status-banner.unhealthy { background: #3a1a1a; border-color: #ff6b6b; }
          .video-container { text-align: center; margin-bottom: 20px; }
          img { max-width: 100%; height: auto; border: 2px solid #333; }
          .stats { background: #111; border: 2px solid #333; padding: 20px; border-radius: 8px; }
          .stats h2 { margin-top: 0; color: #4CAF50; }
          .stat-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 15px; }
          .stat-box { background: #222; padding: 15px; border-radius: 5px; border-left: 4px solid #4CAF50; }
          .stat-label { font-size: 12px; color: #aaa; text-transform: uppercase; }
          .stat-value { font-size: 24px; font-weight: bold; margin-top: 5px; }
          .info { color: #aaa; text-align: center; margin-top: 20px; font-size: 14px; }
        </style>
        <script>
          function updateStats() {
            fetch('/api/stats')
              .then(response => response.json())
              .then(data => {
                const banner = document.getElementById('status-banner');
                const healthText = document.getElementById('health-status');
                healthText.textContent = data.health.toUpperCase();
                banner.className = 'status-banner ' + data.health;
                
                document.getElementById('lux').textContent = data.lux.toFixed(1) + ' lux';
                document.getElementById('exposure').textContent = data.exposure + ' μs';
                document.getElementById('gain').textContent = data.gain.toFixed(2) + 'x';
                document.getElementById('temp').textContent = data.temperature + 'K';
                document.getElementById('timestamp').textContent = new Date(data.timestamp).toLocaleTimeString();
              })
              .catch(err => {
                console.error('Stats update failed:', err);
                document.getElementById('health-status').textContent = 'ERROR';
                document.getElementById('status-banner').className = 'status-banner unhealthy';
              });
          }
          
          setInterval(updateStats, 1000);
          updateStats();
        </script>
      </head>
      <body>
        <div class="container">
          <h1>motionOne - Production IR Camera</h1>
          
          <div id="status-banner" class="status-banner">
            <strong>System Status:</strong> <span id="health-status">INITIALIZING</span><br>
            Production mode with watchdog monitoring and auto-recovery
          </div>
          
          <div class="video-container">
            <img src="/video_feed" alt="Live Camera Feed">
          </div>
          
          <div class="stats">
            <h2>📊 Live Sensor Data</h2>
            <div class="stat-row">
              <div class="stat-box">
                <div class="stat-label">Ambient Light</div>
                <div class="stat-value" id="lux">--</div>
              </div>
              <div class="stat-box">
                <div class="stat-label">Exposure Time</div>
                <div class="stat-value" id="exposure">--</div>
              </div>
              <div class="stat-box">
                <div class="stat-label">Analog Gain</div>
                <div class="stat-value" id="gain">--</div>
              </div>
            </div>
            <div class="stat-row">
              <div class="stat-box">
                <div class="stat-label">Color Temperature</div>
                <div class="stat-value" id="temp">--</div>
              </div>
              <div class="stat-box">
                <div class="stat-label">Last Update</div>
                <div class="stat-value" id="timestamp" style="font-size: 16px;">--</div>
              </div>
              <div class="stat-box">
                <div class="stat-label">Resolution</div>
                <div class="stat-value" style="font-size: 18px;">1280x720</div>
              </div>
            </div>
          </div>
          
          <div class="info">
            Camera: OV5647 3.6mm IR 1080P | 720p @ 15fps | 180° rotation<br>
            Production mode: Error handling, Watchdog, Auto-recovery, Health monitoring
          </div>
        </div>
      </body>
    </html>
    """

@app.route('/video_feed')
def video_feed():
    if not state.camera_ready or not state.output:
        return "Camera not ready", 503
    
    return Response(generate_frames(state.output),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/stats')
def api_stats():
    """API endpoint for live stats and health"""
    return jsonify(state.current_metadata)

@app.route('/health')
def health():
    """Health check endpoint for monitoring"""
    if not state.camera_ready:
        return jsonify({"status": "unhealthy", "reason": "camera not initialized"}), 503

    frame_age = time.time() - state.last_frame_time if state.last_frame_time > 0 else 999

    if frame_age > Config.MAX_FRAME_AGE:
        return jsonify({
            "status": "unhealthy",
            "reason": f"no frames for {frame_age:.1f}s"
        }), 503

    return jsonify({
        "status": "healthy",
        "frame_age": round(frame_age, 2),
        "error_count": state.error_count
    }), 200

def get_system_diagnostics():
    """Gather comprehensive system diagnostics"""
    diagnostics = {
        "uptime": int(time.time() - state.start_time),
        "voltage": {"status": "unknown", "throttled": "unknown"},
        "temperature": {"cpu": 0},
        "network": {"interface": "unknown", "status": "unknown"},
        "memory": {"used_mb": 0, "free_mb": 0},
        "errors": []
    }

    try:
        # Get throttling/voltage status
        result = subprocess.run(['vcgencmd', 'get_throttled'],
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            throttled = result.stdout.strip()
            diagnostics["voltage"]["throttled"] = throttled
            # Parse throttle value
            match = re.search(r'throttled=0x([0-9A-Fa-f]+)', throttled)
            if match:
                value = int(match.group(1), 16)
                if value == 0:
                    diagnostics["voltage"]["status"] = "ok"
                elif value & 0x1:
                    diagnostics["voltage"]["status"] = "under-voltage NOW"
                    diagnostics["errors"].append("Under-voltage detected")
                elif value & 0x10000:
                    diagnostics["voltage"]["status"] = "under-voltage occurred"
                else:
                    diagnostics["voltage"]["status"] = f"throttled (0x{value:x})"
    except Exception as e:
        diagnostics["errors"].append(f"Voltage check failed: {e}")

    try:
        # Get CPU temperature
        result = subprocess.run(['vcgencmd', 'measure_temp'],
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            match = re.search(r'temp=([\d.]+)', result.stdout)
            if match:
                diagnostics["temperature"]["cpu"] = float(match.group(1))
    except Exception as e:
        diagnostics["errors"].append(f"Temperature check failed: {e}")

    try:
        # Get network interface info
        result = subprocess.run(['ip', 'addr', 'show'],
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            # Look for wlan1 (USB dongle) or wlan0
            for line in result.stdout.split('\n'):
                if 'wlan1' in line and 'UP' in line:
                    diagnostics["network"]["interface"] = "wlan1 (USB)"
                    diagnostics["network"]["status"] = "up"
                elif 'wlan0' in line and 'UP' in line:
                    diagnostics["network"]["interface"] = "wlan0 (built-in)"
                    diagnostics["network"]["status"] = "up"
    except Exception as e:
        diagnostics["errors"].append(f"Network check failed: {e}")

    try:
        # Get memory info
        result = subprocess.run(['free', '-m'],
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 4:
                    diagnostics["memory"]["used_mb"] = int(parts[2])
                    diagnostics["memory"]["free_mb"] = int(parts[3])
    except Exception as e:
        diagnostics["errors"].append(f"Memory check failed: {e}")

    return diagnostics

@app.route('/logs')
def logs():
    """Web-based log viewer"""
    level_filter = request.args.get('level', 'all').upper()
    search = request.args.get('search', '')

    logs_html = """
    <html>
      <head>
        <title>motionOne - System Logs</title>
        <style>
          body { background: #000; margin: 0; font-family: 'Courier New', monospace; color: #0f0; }
          .container { max-width: 1920px; margin: 0 auto; padding: 20px; }
          .header { background: #111; border: 2px solid #0f0; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
          .header h1 { margin: 0 0 10px 0; color: #0f0; }
          .controls { display: flex; gap: 10px; align-items: center; }
          .controls select, .controls input { padding: 8px; background: #222; color: #0f0; border: 1px solid #0f0; }
          .controls button { padding: 8px 16px; background: #0f0; color: #000; border: none; cursor: pointer; font-weight: bold; }
          .log-container { background: #000; border: 2px solid #333; padding: 15px; border-radius: 8px; max-height: 70vh; overflow-y: auto; }
          .log-entry { padding: 8px; border-left: 3px solid #333; margin-bottom: 5px; font-size: 13px; }
          .log-entry.INFO { border-left-color: #0f0; }
          .log-entry.WARNING { border-left-color: #FFA726; color: #FFA726; }
          .log-entry.ERROR { border-left-color: #ff6b6b; color: #ff6b6b; }
          .log-entry.CRITICAL { border-left-color: #f00; color: #f00; background: #300; }
          .timestamp { color: #666; margin-right: 10px; }
          .level { font-weight: bold; margin-right: 10px; display: inline-block; min-width: 60px; }
          .back-link { color: #0f0; text-decoration: none; margin-left: 20px; }
          .back-link:hover { text-decoration: underline; }
        </style>
        <script>
          function filterLogs() {
            window.location.href = '/logs?level=' + document.getElementById('level').value + '&search=' + document.getElementById('search').value;
          }
          function autoRefresh() {
            setTimeout(() => location.reload(), 5000);
          }
          autoRefresh();
        </script>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h1>📋 System Logs <a href="/" class="back-link">← Back to Camera</a> <a href="/diagnostics" class="back-link">Diagnostics →</a></h1>
            <div class="controls">
              <label>Level:</label>
              <select id="level" onchange="filterLogs()">
                <option value="all" {all_selected}>All</option>
                <option value="info" {info_selected}>Info</option>
                <option value="warning" {warning_selected}>Warning</option>
                <option value="error" {error_selected}>Error+</option>
              </select>
              <label>Search:</label>
              <input type="text" id="search" value="{search_value}" placeholder="Search logs...">
              <button onclick="filterLogs()">Filter</button>
              <span style="color: #666; margin-left: auto;">Auto-refresh every 5s</span>
            </div>
          </div>
          <div class="log-container">
    """

    # Filter logs
    filtered_logs = []
    for log in state.log_buffer:
        # Level filter
        if level_filter == 'ERROR' and log['level'] not in ['ERROR', 'CRITICAL']:
            continue
        elif level_filter != 'ALL' and log['level'] != level_filter:
            continue

        # Search filter
        if search and search.lower() not in log['message'].lower():
            continue

        filtered_logs.append(log)

    # Generate log entries
    for log in reversed(filtered_logs):  # Most recent first
        ts = datetime.fromisoformat(log['timestamp']).strftime('%H:%M:%S')
        logs_html += f"""
            <div class="log-entry {log['level']}">
              <span class="timestamp">{ts}</span>
              <span class="level">{log['level']}</span>
              {log['message']}
            </div>
        """

    if not filtered_logs:
        logs_html += '<div style="color: #666; text-align: center; padding: 40px;">No logs match filters</div>'

    logs_html += """
          </div>
        </div>
      </body>
    </html>
    """

    # Replace placeholders
    logs_html = logs_html.replace('{all_selected}', 'selected' if level_filter == 'ALL' else '')
    logs_html = logs_html.replace('{info_selected}', 'selected' if level_filter == 'INFO' else '')
    logs_html = logs_html.replace('{warning_selected}', 'selected' if level_filter == 'WARNING' else '')
    logs_html = logs_html.replace('{error_selected}', 'selected' if level_filter == 'ERROR' else '')
    logs_html = logs_html.replace('{search_value}', search)

    return logs_html

@app.route('/diagnostics')
def diagnostics():
    """System diagnostics dashboard"""
    diag = get_system_diagnostics()
    uptime_str = f"{diag['uptime'] // 3600}h {(diag['uptime'] % 3600) // 60}m"

    voltage_color = '#4CAF50' if diag['voltage']['status'] == 'ok' else '#ff6b6b'

    return f"""
    <html>
      <head>
        <title>motionOne - System Diagnostics</title>
        <style>
          body {{ background: #000; margin: 0; font-family: Arial, sans-serif; color: #fff; }}
          .container {{ max-width: 1920px; margin: 0 auto; padding: 20px; }}
          .header {{ background: #111; border: 2px solid #4CAF50; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
          .header h1 {{ margin: 0; color: #4CAF50; }}
          .back-link {{ color: #4CAF50; text-decoration: none; margin-left: 20px; font-size: 16px; }}
          .back-link:hover {{ text-decoration: underline; }}
          .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
          .card {{ background: #111; border: 2px solid #333; padding: 20px; border-radius: 8px; }}
          .card h2 {{ margin-top: 0; color: #4CAF50; font-size: 18px; }}
          .stat-row {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #222; }}
          .stat-label {{ color: #aaa; }}
          .stat-value {{ font-weight: bold; }}
          .error-list {{ background: #3a1a1a; border-left: 4px solid #ff6b6b; padding: 15px; border-radius: 5px; }}
          .success {{ color: #4CAF50; }}
          .warning {{ color: #FFA726; }}
          .error {{ color: #ff6b6b; }}
        </style>
        <script>
          setTimeout(() => location.reload(), 5000);
        </script>
      </head>
      <body>
        <div class="container">
          <div class="header">
            <h1>🔧 System Diagnostics <a href="/" class="back-link">← Back to Camera</a> <a href="/logs" class="back-link">Logs →</a></h1>
          </div>

          <div class="grid">
            <div class="card">
              <h2>⚡ Power & Performance</h2>
              <div class="stat-row">
                <span class="stat-label">Power Status:</span>
                <span class="stat-value" style="color: {voltage_color}">{diag['voltage']['status']}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Throttle Status:</span>
                <span class="stat-value">{diag['voltage']['throttled']}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">CPU Temperature:</span>
                <span class="stat-value">{diag['temperature']['cpu']:.1f}°C</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Uptime:</span>
                <span class="stat-value success">{uptime_str}</span>
              </div>
            </div>

            <div class="card">
              <h2>🌐 Network</h2>
              <div class="stat-row">
                <span class="stat-label">Active Interface:</span>
                <span class="stat-value success">{diag['network']['interface']}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Status:</span>
                <span class="stat-value success">{diag['network']['status']}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Memory Used:</span>
                <span class="stat-value">{diag['memory']['used_mb']} MB</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Memory Free:</span>
                <span class="stat-value">{diag['memory']['free_mb']} MB</span>
              </div>
            </div>

            <div class="card">
              <h2>📹 Camera Status</h2>
              <div class="stat-row">
                <span class="stat-label">Camera Ready:</span>
                <span class="stat-value {'success' if state.camera_ready else 'error'}">{'Yes' if state.camera_ready else 'No'}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Health:</span>
                <span class="stat-value success">{state.current_metadata['health']}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Error Count:</span>
                <span class="stat-value {'error' if state.error_count > 0 else 'success'}">{state.error_count}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Frame Age:</span>
                <span class="stat-value">{(time.time() - state.last_frame_time):.2f}s</span>
              </div>
            </div>

            <div class="card">
              <h2>⚙️ Configuration</h2>
              <div class="stat-row">
                <span class="stat-label">Resolution:</span>
                <span class="stat-value">{Config.CAMERA_RESOLUTION[0]}x{Config.CAMERA_RESOLUTION[1]}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Frame Rate:</span>
                <span class="stat-value">{Config.CAMERA_FPS} fps</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">JPEG Quality:</span>
                <span class="stat-value">{Config.JPEG_QUALITY}</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">Watchdog:</span>
                <span class="stat-value">{Config.WATCHDOG_TIMEOUT}s</span>
              </div>
            </div>
          </div>

          {"<div class='error-list'><h3 style='margin-top:0;'>⚠️ System Errors</h3>" + '<br>'.join(diag['errors']) + "</div>" if diag['errors'] else "<div style='text-align:center;color:#4CAF50;padding:20px;font-size:18px;'>✅ No system errors detected</div>"}

          <div style="text-align: center; color: #666; margin-top: 20px; font-size: 14px;">
            Auto-refresh every 5 seconds
          </div>
        </div>
      </body>
    </html>
    """

def signal_handler(signum, frame):
    """Graceful shutdown handler"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown()

def shutdown():
    """Clean shutdown procedure"""
    logger.info("Initiating shutdown...")
    state.shutdown_event.set()
    
    # Stop camera
    if state.picam2:
        try:
            logger.info("Stopping camera recording...")
            state.picam2.stop_recording()
            state.picam2.close()
            logger.info("Camera stopped")
        except Exception as e:
            logger.error(f"Error stopping camera: {e}")
    
    # Wait for threads
    if state.metadata_thread and state.metadata_thread.is_alive():
        logger.info("Waiting for metadata thread...")
        state.metadata_thread.join(timeout=5)
    
    if state.health_thread and state.health_thread.is_alive():
        logger.info("Waiting for health thread...")
        state.health_thread.join(timeout=5)
    
    logger.info("Shutdown complete")

def main():
    """Main entry point with full error handling"""
    logger.info("=" * 70)
    logger.info("motionOne Production Camera Server")
    logger.info("=" * 70)
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Configuration: {Config.CAMERA_RESOLUTION} @ {Config.CAMERA_FPS}fps, Quality {Config.JPEG_QUALITY}")
    logger.info("=" * 70)
    
    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Initialize camera
        state.picam2, state.output = initialize_camera()
        
        if not state.picam2 or not state.output:
            logger.critical("Failed to initialize camera after all retries")
            logger.critical("Exiting - systemd will handle restart")
            return 1
        
        state.camera_ready = True
        state.last_frame_time = time.time()
        
        # Start monitoring threads
        state.metadata_thread = threading.Thread(
            target=metadata_update_thread,
            daemon=True,
            name="metadata-thread"
        )
        state.metadata_thread.start()
        
        state.health_thread = threading.Thread(
            target=health_check_thread,
            daemon=True,
            name="health-thread"
        )
        state.health_thread.start()
        
        logger.info("✓ All systems operational")
        logger.info(f"✓ Web interface: http://172.16.0.28:8080")
        logger.info(f"✓ Health endpoint: http://172.16.0.28:8080/health")
        logger.info(f"✓ Watchdog timeout: {Config.WATCHDOG_TIMEOUT}s")
        logger.info("=" * 70)
        
        # Start Flask server
        app.run(
            host='0.0.0.0',
            port=8080,
            threaded=True,
            debug=False,
            use_reloader=False
        )
        
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        return 1
    finally:
        shutdown()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
