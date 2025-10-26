#!/usr/bin/env python3
"""
BEEPER KEEPER 10000 - Dual Camera Monitoring System
==================================================

A Flask-based web UI for monitoring dual camera streams via MediaMTX WebRTC.

Features:
- CSI Camera (IR Night Vision) + USB Webcam streaming
- Side-by-side or single camera view modes
- Real-time system and sensor monitoring
- Environmental sensor support (BME680)
- CPU temperature and system stats
- Camera metadata display (exposure, gain, lux)

Hardware Requirements:
- Raspberry Pi (tested on Pi 3B+)
- CSI camera module (e.g., OV5647 IR)
- USB webcam (optional, for dual camera setup)
- BME680 sensor (optional, for environmental monitoring)

Dependencies:
- Flask (web framework)
- psutil (system monitoring)
- adafruit-circuitpython-bme680 (optional, for BME680 sensor)

Configuration:
- Copy config.example.py to config.py and update with your settings
- Set RASPBERRY_PI_IP to your Pi's IP address
- Configure sensor I2C addresses if needed

Author: YOUR_GITHUB_USERNAME
License: MIT
Repository: https://github.com/YOUR_GITHUB_USERNAME/beeperKeeper
"""

from flask import Flask, Response, jsonify, render_template_string, send_file
import time
import threading
import psutil
from datetime import datetime
import os

# Load configuration
try:
    from config import *
except ImportError:
    print("WARNING: config.py not found. Using default configuration.")
    print("Copy config.example.py to config.py and update with your settings.")
    # Default configuration
    RASPBERRY_PI_IP = "YOUR_PI_IP_HERE"
    WEBRTC_PORT = 8889
    WEB_UI_PORT = 8080
    BME680_ENABLED = True
    BME680_I2C_ADDRESS = 0x76
    UPDATE_INTERVAL_SECONDS = 2

app = Flask(__name__)

# Global sensor data
sensor_data = {
    'camera': {},
    'cpu_temp': 0,
    'system': {},
    'i2c_sensors': {},
    'last_update': 0
}

# Sensor instances
bme680 = None

# ============= SENSOR INITIALIZATION =============

def init_i2c_sensors():
    """
    Initialize I2C environmental sensors.

    Attempts to initialize BME680 sensor for temperature, humidity, pressure, and air quality monitoring.
    Falls back gracefully if sensor is not available or BME680_ENABLED is False in config.
    """
    global bme680
    if not BME680_ENABLED:
        print("ℹ BME680 sensor disabled in configuration")
        return

    try:
        import board
        import busio
        import adafruit_bme680
        i2c = busio.I2C(board.SCL, board.SDA)
        try:
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=BME680_I2C_ADDRESS)
            print(f"✓ BME680 sensor detected at 0x{BME680_I2C_ADDRESS:02x}")
        except:
            # Try alternate address
            alt_address = 0x77 if BME680_I2C_ADDRESS == 0x76 else 0x76
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=alt_address)
            print(f"✓ BME680 sensor detected at 0x{alt_address:02x}")
    except Exception as e:
        print(f"✗ I2C initialization failed: {e}")

# ============= DATA COLLECTION =============

def get_cpu_temp():
    """
    Read CPU temperature from thermal zone.

    Returns:
        float: CPU temperature in Celsius, or None if unable to read
    """
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return None

def get_camera_metadata():
    """
    Extract camera sensor metadata from rpicam-vid JSON output.

    Reads the last complete JSON object from /tmp/camera_metadata.json which is
    continuously written by rpicam-vid. Provides real-time camera sensor information.

    Returns:
        dict: Camera metadata including:
            - exposure_time: Shutter speed in microseconds
            - analogue_gain: Sensor analogue gain multiplier
            - digital_gain: Digital gain multiplier
            - colour_gains: White balance gains (red, blue)
            - lux: Light level estimate (if available)
            - colour_temp: Color temperature in Kelvin (if available)
    """
    try:
        import json
        with open('/tmp/camera_metadata.json', 'rb') as f:
            f.seek(0, 2)
            file_size = f.tell()
            read_size = min(5000, file_size)
            f.seek(max(0, file_size - read_size))
            tail_data = f.read().decode('utf-8', errors='ignore')
        
        last_brace = tail_data.rfind('}')
        if last_brace == -1:
            return {}
        
        search_start = max(0, last_brace - 2000)
        chunk = tail_data[search_start:last_brace+1]
        first_brace = chunk.rfind('{')
        if first_brace == -1:
            return {}
        
        metadata = json.loads(chunk[first_brace:])
        
        return {
            'exposure_time': metadata.get('ExposureTime', 0),
            'analogue_gain': round(metadata.get('AnalogueGain', 0), 2),
            'digital_gain': round(metadata.get('DigitalGain', 0), 2),
            'colour_gains': metadata.get('ColourGains', (0, 0)),
            'lux': round(metadata.get('Lux', 0), 2) if 'Lux' in metadata else None,
            'colour_temp': metadata.get('ColourTemperature', None)
        }
    except:
        return {}

def get_i2c_sensor_data():
    """
    Read environmental data from BME680 sensor.

    Returns:
        dict: Sensor readings including:
            - temperature: Ambient temperature in Celsius
            - humidity: Relative humidity percentage
            - pressure: Atmospheric pressure in hPa
            - gas: Gas resistance in Ohms (air quality indicator)
            - altitude: Estimated altitude in meters
        Empty dict if sensor not available or read fails.
    """
    if not bme680:
        return {}
    try:
        return {
            'bme680': {
                'temperature': round(bme680.temperature, 2),
                'humidity': round(bme680.humidity, 2),
                'pressure': round(bme680.pressure, 2),
                'gas': round(bme680.gas, 2),
                'altitude': round(bme680.altitude, 2)
            }
        }
    except:
        return {}

def get_system_stats():
    """
    Collect system resource usage statistics.

    Returns:
        dict: System metrics including:
            - cpu_percent: CPU usage percentage
            - memory_percent: RAM usage percentage
            - memory_used_mb: Used RAM in megabytes
            - memory_total_mb: Total RAM in megabytes
            - disk_percent: Disk usage percentage
            - disk_used_gb: Used disk space in gigabytes
            - disk_total_gb: Total disk space in gigabytes
            - uptime_seconds: System uptime in seconds
    """
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        'cpu_percent': round(cpu_percent, 1),
        'memory_percent': round(mem.percent, 1),
        'memory_used_mb': round(mem.used / 1024 / 1024, 1),
        'memory_total_mb': round(mem.total / 1024 / 1024, 1),
        'disk_percent': round(disk.percent, 1),
        'disk_used_gb': round(disk.used / 1024 / 1024 / 1024, 1),
        'disk_total_gb': round(disk.total / 1024 / 1024 / 1024, 1),
        'uptime_seconds': int(time.time() - psutil.boot_time())
    }

def update_sensor_data():
    """Update all sensor data (background thread)"""
    while True:
        try:
            sensor_data['cpu_temp'] = get_cpu_temp()
            sensor_data['camera'] = get_camera_metadata()
            sensor_data['system'] = get_system_stats()
            sensor_data['i2c_sensors'] = get_i2c_sensor_data()
            sensor_data['last_update'] = time.time()
        except Exception as e:
            print(f"Error updating sensor data: {e}")
        time.sleep(2)

# ============= API ENDPOINTS =============

@app.route('/api/metrics')
def api_metrics():
    """JSON metrics for web UI"""
    return jsonify({
        'timestamp': datetime.now().isoformat(),
        'cpu_temperature': sensor_data['cpu_temp'],
        'camera': sensor_data['camera'],
        'system': sensor_data['system'],
        'i2c_sensors': sensor_data['i2c_sensors'],
        'last_update': sensor_data['last_update']
    })

@app.route('/chicken_image')
def chicken_image():
    """Serve the chicken of despair mascot image"""
    image_path = os.path.join(os.path.dirname(__file__), 'chicken_of_despair.png')
    return send_file(image_path, mimetype='image/png')

@app.route('/')
def index():
    """Main web interface with dual camera support"""
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>BEEPER KEEPER 10000</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: #f1f5f9;
            padding: 20px;
            min-height: 100vh;
            position: relative;
            overflow-x: hidden;
        }
        
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.08;
            z-index: 0;
            pointer-events: none;
            background-image: 
                /* Random chicken emojis at different sizes */
                radial-gradient(circle at 10% 15%, transparent 1.8%, transparent 2%),
                radial-gradient(circle at 35% 8%, transparent 2.5%, transparent 3%),
                radial-gradient(circle at 65% 25%, transparent 1.2%, transparent 1.5%),
                radial-gradient(circle at 88% 12%, transparent 3%, transparent 3.5%),
                radial-gradient(circle at 15% 42%, transparent 2.2%, transparent 2.5%),
                radial-gradient(circle at 48% 35%, transparent 1.5%, transparent 2%),
                radial-gradient(circle at 78% 45%, transparent 2.8%, transparent 3%),
                radial-gradient(circle at 25% 68%, transparent 1.8%, transparent 2%),
                radial-gradient(circle at 52% 62%, transparent 2.5%, transparent 3%),
                radial-gradient(circle at 85% 72%, transparent 1.3%, transparent 1.5%),
                radial-gradient(circle at 8% 85%, transparent 3.2%, transparent 3.5%),
                radial-gradient(circle at 38% 88%, transparent 1.6%, transparent 2%),
                radial-gradient(circle at 72% 92%, transparent 2.3%, transparent 2.8%),
                radial-gradient(circle at 92% 88%, transparent 1.9%, transparent 2.2%);
        }
        
        body::after {
            content: '🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔 🐔';
            position: fixed;
            top: 0;
            left: 0;
            width: 200%;
            height: 200%;
            font-size: 40px;
            line-height: 80px;
            opacity: 0.06;
            z-index: 0;
            pointer-events: none;
            transform: rotate(-15deg);
            word-spacing: 50px;
            letter-spacing: 60px;
        }
        
        .header, .controls, .video-grid, .metrics-grid {
            position: relative;
            z-index: 1;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
        }

        .header img {
            width: 150px;
            height: auto;
            margin-bottom: 15px;
            filter: drop-shadow(0 0 10px rgba(96, 165, 250, 0.3));
        }

        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            letter-spacing: 2px;
            color: #60a5fa;
            text-shadow: 0 0 20px rgba(96, 165, 250, 0.5);
        }
        
        .controls {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        
        .btn-primary {
            background: #60a5fa;
            color: #0f172a;
        }
        
        .btn-primary:hover {
            background: #3b82f6;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(96, 165, 250, 0.4);
        }
        
        .btn-secondary {
            background: #cbd5e1;
            color: #0f172a;
        }
        
        .btn-secondary:hover {
            background: #94a3b8;
            transform: translateY(-2px);
        }
        
        .btn.active {
            background: #10b981;
            color: white;
        }
        
        .video-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .video-grid.dual {
            grid-template-columns: 1fr 1fr;
        }
        
        .video-container {
            background: #000;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            border: 3px solid #93c5fd;
            position: relative;
        }
        
        .video-container.hidden {
            display: none;
        }
        
        .video-label {
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(15, 23, 42, 0.8);
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            color: #60a5fa;
            z-index: 10;
        }
        
        iframe {
            width: 100%;
            height: 500px;
            border: none;
            display: block;
        }
        
        .audio-control {
            position: absolute;
            bottom: 10px;
            right: 10px;
            z-index: 10;
        }
        
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }
        
        .card {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.3);
        }
        
        .card:nth-child(1) { border: 3px solid #d1d5db; }  /* light gray - System Health */
        .card:nth-child(2) { border: 3px solid #93c5fd; }  /* light blue - Camera Sensor */
        .card:nth-child(3) { border: 3px solid #e5e7eb; }  /* lighter gray - Environmental */
        .card:nth-child(4) { border: 3px solid #bae6fd; }  /* lightest blue - System Stats */
        
        .card h2 {
            font-size: 1.2rem;
            margin-bottom: 15px;
            color: #60a5fa;
            font-weight: 600;
        }
        
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .metric:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            color: #cbd5e1;
            font-size: 14px;
        }
        
        .metric-value {
            color: #f1f5f9;
            font-weight: 600;
            font-size: 14px;
        }
        
        .status-good { color: #10b981; }
        .status-warn { color: #f59e0b; }
        .status-error { color: #ef4444; }
        
        @media (max-width: 1024px) {
            .video-grid.dual {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <img src="/chicken_image" alt="Chicken of Despair">
        <h1>BEEPER KEEPER 10000</h1>
    </div>
    
    <div class="controls">
        <button class="btn btn-primary active" onclick="setView('dual')">Dual View</button>
        <button class="btn btn-secondary" onclick="setView('csi')">IR Camera Only</button>
        <button class="btn btn-secondary" onclick="setView('usb')">USB Camera Only</button>
        <button class="btn btn-secondary" id="audioBtn" onclick="toggleAudio()">Audio: OFF</button>
    </div>
    
    <div class="video-grid dual" id="videoGrid">
        <div class="video-container" id="csiContainer">
            <div class="video-label">IR CAMERA (CSI)</div>
            <iframe id="csiFrame" src="http://''' + RASPBERRY_PI_IP + ''':''' + str(WEBRTC_PORT) + '''/csi_camera"></iframe>
        </div>
        <div class="video-container" id="usbContainer">
            <div class="video-label">USB WEBCAM</div>
            <iframe id="usbFrame" src="http://''' + RASPBERRY_PI_IP + ''':''' + str(WEBRTC_PORT) + '''/usb_camera"></iframe>
        </div>
    </div>
    
    <div class="metrics-grid">
        <div class="card">
            <h2>System Health</h2>
            <div id="systemHealth">Loading...</div>
        </div>
        
        <div class="card">
            <h2>Camera Sensor</h2>
            <div id="cameraSensor">Loading...</div>
        </div>
        
        <div class="card">
            <h2>Environmental Sensors</h2>
            <div id="envSensors">Loading...</div>
        </div>
        
        <div class="card">
            <h2>System Stats</h2>
            <div id="systemStats">Loading...</div>
        </div>
    </div>
    
    <script>
        let currentView = 'dual';
        let audioEnabled = false;
        
        function setView(view) {
            currentView = view;
            const videoGrid = document.getElementById('videoGrid');
            const csiContainer = document.getElementById('csiContainer');
            const usbContainer = document.getElementById('usbContainer');
            
            // Update button states
            document.querySelectorAll('.controls .btn-primary, .controls .btn-secondary').forEach(btn => {
                if (btn.textContent.includes('Audio')) return;
                btn.className = 'btn btn-secondary';
            });
            
            if (view === 'dual') {
                videoGrid.className = 'video-grid dual';
                csiContainer.className = 'video-container';
                usbContainer.className = 'video-container';
                event.target.className = 'btn btn-primary active';
            } else if (view === 'csi') {
                videoGrid.className = 'video-grid';
                csiContainer.className = 'video-container';
                usbContainer.className = 'video-container hidden';
                event.target.className = 'btn btn-primary active';
            } else if (view === 'usb') {
                videoGrid.className = 'video-grid';
                csiContainer.className = 'video-container hidden';
                usbContainer.className = 'video-container';
                event.target.className = 'btn btn-primary active';
            }
        }
        
        function toggleAudio() {
            audioEnabled = !audioEnabled;
            const audioBtn = document.getElementById('audioBtn');
            const usbFrame = document.getElementById('usbFrame');
            
            if (audioEnabled) {
                audioBtn.textContent = 'Audio: ON';
                audioBtn.className = 'btn btn-primary active';
                // Reload iframe to enable audio
                usbFrame.src = usbFrame.src;
            } else {
                audioBtn.textContent = 'Audio: OFF';
                audioBtn.className = 'btn btn-secondary';
            }
        }
        
        function updateMetrics() {
            fetch('/api/metrics')
                .then(response => response.json())
                .then(data => {
                    // System Health
                    const cpu_temp = data.cpu_temperature || 0;
                    const temp_class = cpu_temp > 70 ? 'status-error' : (cpu_temp > 60 ? 'status-warn' : 'status-good');
                    document.getElementById('systemHealth').innerHTML = `
                        <div class="metric">
                            <span class="metric-label">CPU Temperature</span>
                            <span class="metric-value ${temp_class}">${cpu_temp.toFixed(1)}°C</span>
                        </div>
                    `;
                    
                    // Camera Sensor
                    const cam = data.camera || {};
                    let cameraHtml = '';
                    if (Object.keys(cam).length === 0) {
                        cameraHtml = '<div class="metric status-warn">No metadata available</div>';
                    } else {
                        cameraHtml = `
                            <div class="metric">
                                <span class="metric-label">Exposure Time</span>
                                <span class="metric-value">${cam.exposure_time}µs</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">Analogue Gain</span>
                                <span class="metric-value">${cam.analogue_gain}x</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">Lux</span>
                                <span class="metric-value">${cam.lux !== null ? cam.lux : 'N/A'}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">Color Temp</span>
                                <span class="metric-value">${cam.colour_temp || 'N/A'}K</span>
                            </div>
                        `;
                    }
                    document.getElementById('cameraSensor').innerHTML = cameraHtml;
                    
                    // Environmental Sensors
                    const env = data.i2c_sensors?.bme680 || {};
                    let envHtml = '';
                    if (Object.keys(env).length === 0) {
                        envHtml = '<div class="metric status-warn">No sensor data</div>';
                    } else {
                        envHtml = `
                            <div class="metric">
                                <span class="metric-label">Temperature</span>
                                <span class="metric-value">${env.temperature}°C</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">Humidity</span>
                                <span class="metric-value">${env.humidity}%</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">Pressure</span>
                                <span class="metric-value">${env.pressure} hPa</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">Gas (Air Quality)</span>
                                <span class="metric-value">${env.gas} Ω</span>
                            </div>
                        `;
                    }
                    document.getElementById('envSensors').innerHTML = envHtml;
                    
                    // System Stats
                    const sys = data.system || {};
                    const cpu_class = sys.cpu_percent > 85 ? 'status-error' : (sys.cpu_percent > 70 ? 'status-warn' : 'status-good');
                    const mem_class = sys.memory_percent > 85 ? 'status-error' : (sys.memory_percent > 70 ? 'status-warn' : 'status-good');
                    
                    const uptime_hours = Math.floor(sys.uptime_seconds / 3600);
                    const uptime_mins = Math.floor((sys.uptime_seconds % 3600) / 60);
                    
                    document.getElementById('systemStats').innerHTML = `
                        <div class="metric">
                            <span class="metric-label">CPU Usage</span>
                            <span class="metric-value ${cpu_class}">${sys.cpu_percent}%</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Memory Usage</span>
                            <span class="metric-value ${mem_class}">${sys.memory_percent}%</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Disk Usage</span>
                            <span class="metric-value">${sys.disk_percent}%</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Uptime</span>
                            <span class="metric-value">${uptime_hours}h ${uptime_mins}m</span>
                        </div>
                    `;
                })
                .catch(error => console.error('Error fetching metrics:', error));
        }
        
        // Update every 2 seconds
        updateMetrics();
        setInterval(updateMetrics, 2000);
    </script>
</body>
</html>
    ''')

# ============= MAIN =============

if __name__ == '__main__':
    print("\n=== BEEPER KEEPER 10000 - Dual Camera System ===\n")
    
    # Initialize sensors
    init_i2c_sensors()
    
    # Start background data collection
    sensor_thread = threading.Thread(target=update_sensor_data, daemon=True)
    sensor_thread.start()
    
    print(f"\n✓ Monitoring server starting on http://0.0.0.0:{WEB_UI_PORT}")
    print(f"  IR Camera: http://{RASPBERRY_PI_IP}:{WEBRTC_PORT}/csi_camera")
    print(f"  USB Camera: http://{RASPBERRY_PI_IP}:{WEBRTC_PORT}/usb_camera")
    print(f"  Web UI: http://{RASPBERRY_PI_IP}:{WEB_UI_PORT}\n")

    app.run(host='0.0.0.0', port=WEB_UI_PORT, threaded=True)
