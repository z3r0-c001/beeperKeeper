#!/usr/bin/env python3
"""
BEEPER KEEPER 10000 - Dual Camera Monitoring System
- CSI Camera (IR Night Vision) + USB Webcam
- Side-by-side or single view
- Audio control for USB webcam
- Real-time sensor monitoring
"""

from flask import Flask, Response, jsonify, render_template_string, send_file
import time
import threading
import psutil
from datetime import datetime
import os
import math
import json
import paho.mqtt.client as mqtt

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

# MQTT Configuration
MQTT_BROKER = "172.16.0.7"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "beeper_camera_monitor"
mqtt_client = None

# BME680 Air Quality Configuration
BME680_BASELINE_FILE = '/tmp/bme680_baseline.json'
bme680_baseline = {
    'gas_baseline': None,  # Baseline gas resistance in clean air
    'hum_baseline': 40.0,  # Baseline humidity (40% is typical indoor)
    'calibration_time': None,
    'samples_collected': 0
}

# Air Quality thresholds (based on compensated gas resistance)
IAQ_THRESHOLDS = {
    'excellent': (0, 50),      # Excellent air quality
    'good': (51, 100),         # Good air quality
    'lightly_polluted': (101, 150),  # Lightly polluted
    'moderately_polluted': (151, 200),  # Moderately polluted
    'heavily_polluted': (201, 250),  # Heavily polluted
    'severely_polluted': (251, 350),  # Severely polluted
    'extremely_polluted': (351, 500)  # Extremely polluted
}

# ============= SENSOR INITIALIZATION =============

def init_i2c_sensors():
    """Auto-detect and initialize I2C sensors"""
    global bme680
    try:
        import board
        import busio
        import adafruit_bme680
        i2c = busio.I2C(board.SCL, board.SDA)
        try:
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=0x76)
            print("✓ BME680 sensor detected at 0x76")
        except:
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=0x77)
            print("✓ BME680 sensor detected at 0x77")

        # Load baseline calibration if available
        load_bme680_baseline()

        # Start baseline calibration if needed
        if bme680_baseline['gas_baseline'] is None:
            print("⚠ BME680: No baseline found. Calibrating in clean air...")
            print("  - Ensure sensor is in clean air environment")
            print("  - Calibration will complete after 30 minutes")
            print("  - IAQ readings will be available after calibration")
        else:
            print(f"✓ BME680: Loaded baseline from {BME680_BASELINE_FILE}")
            print(f"  - Gas baseline: {bme680_baseline['gas_baseline']:.0f} Ω")

    except Exception as e:
        print(f"✗ I2C initialization failed: {e}")

def load_bme680_baseline():
    """Load BME680 baseline calibration from file"""
    global bme680_baseline
    try:
        if os.path.exists(BME680_BASELINE_FILE):
            with open(BME680_BASELINE_FILE, 'r') as f:
                saved_baseline = json.load(f)
                bme680_baseline.update(saved_baseline)
                return True
    except Exception as e:
        print(f"⚠ Could not load BME680 baseline: {e}")
    return False

def save_bme680_baseline():
    """Save BME680 baseline calibration to file"""
    try:
        with open(BME680_BASELINE_FILE, 'w') as f:
            json.dump(bme680_baseline, f)
        return True
    except Exception as e:
        print(f"✗ Could not save BME680 baseline: {e}")
    return False

def calculate_gas_resistance_compensated(gas_raw, humidity):
    """
    Calculate humidity-compensated gas resistance.
    Formula: comp_gas = log(R_gas[Ω]) + 0.04 × log(Ω)/(%rh) × hum[%rh]

    Args:
        gas_raw: Raw gas resistance in Ohms
        humidity: Relative humidity in %

    Returns:
        Compensated gas resistance value
    """
    if gas_raw <= 0:
        return 0

    try:
        log_gas = math.log(gas_raw)
        hum_offset = 0.04 * log_gas * humidity
        comp_gas = log_gas + hum_offset
        return comp_gas
    except:
        return 0

def calculate_iaq(gas_raw, humidity):
    """
    Calculate Indoor Air Quality (IAQ) index from 0-500.
    Lower values = better air quality.

    Based on compensated gas resistance relative to baseline.
    Requires baseline calibration in clean air.

    Args:
        gas_raw: Raw gas resistance in Ohms
        humidity: Relative humidity in %

    Returns:
        IAQ index (0-500), or None if not calibrated
    """
    global bme680_baseline

    # Check if we have a baseline
    if bme680_baseline['gas_baseline'] is None:
        # Collect samples for baseline (30 minutes = 900 samples at 2s intervals)
        if bme680_baseline['samples_collected'] < 900:
            bme680_baseline['samples_collected'] += 1
            return None
        else:
            # Set baseline after 30 minutes
            bme680_baseline['gas_baseline'] = gas_raw
            bme680_baseline['hum_baseline'] = humidity
            bme680_baseline['calibration_time'] = time.time()
            save_bme680_baseline()
            print(f"✓ BME680: Baseline calibrated! Gas={gas_raw:.0f}Ω, Hum={humidity:.1f}%")
            return 50  # Start with "excellent" after calibration

    # Calculate compensated values
    gas_comp = calculate_gas_resistance_compensated(gas_raw, humidity)
    baseline_comp = calculate_gas_resistance_compensated(
        bme680_baseline['gas_baseline'],
        bme680_baseline['hum_baseline']
    )

    if baseline_comp == 0:
        return None

    # Calculate IAQ: ratio of baseline to current (inverted scale)
    # Higher gas resistance = better air quality = lower IAQ
    gas_ratio = baseline_comp / gas_comp if gas_comp > 0 else 1.0

    # Map to 0-500 scale (exponential mapping for sensitivity)
    # gas_ratio: 1.0 = baseline (IAQ 50)
    # gas_ratio: 0.5 = half baseline (IAQ ~200)
    # gas_ratio: 0.25 = quarter baseline (IAQ ~400)
    iaq = 50 + (1.0 - gas_ratio) * 450

    # Clamp to 0-500 range
    iaq = max(0, min(500, iaq))

    return round(iaq, 1)

def get_iaq_classification(iaq):
    """Get air quality classification from IAQ value"""
    if iaq is None:
        return "Calibrating..."

    for classification, (min_val, max_val) in IAQ_THRESHOLDS.items():
        if min_val <= iaq <= max_val:
            return classification.replace('_', ' ').title()

    return "Unknown"

def estimate_co2_equivalent(iaq):
    """
    Estimate CO2 equivalent in ppm from IAQ.
    This is a rough approximation, not precise measurement.

    IAQ mapping (approximate):
    0-50: 400-600 ppm (outdoor/excellent)
    50-100: 600-800 ppm (good)
    100-150: 800-1000 ppm (acceptable)
    150-200: 1000-1500 ppm (moderate)
    200-300: 1500-2500 ppm (poor)
    300-500: 2500-5000 ppm (very poor)
    """
    if iaq is None:
        return None

    # Piecewise linear mapping
    if iaq <= 50:
        co2 = 400 + (iaq / 50) * 200  # 400-600 ppm
    elif iaq <= 100:
        co2 = 600 + ((iaq - 50) / 50) * 200  # 600-800 ppm
    elif iaq <= 150:
        co2 = 800 + ((iaq - 100) / 50) * 200  # 800-1000 ppm
    elif iaq <= 200:
        co2 = 1000 + ((iaq - 150) / 50) * 500  # 1000-1500 ppm
    elif iaq <= 300:
        co2 = 1500 + ((iaq - 200) / 100) * 1000  # 1500-2500 ppm
    else:
        co2 = 2500 + ((iaq - 300) / 200) * 2500  # 2500-5000 ppm

    return round(co2, 0)

# ============= DATA COLLECTION =============

def get_cpu_temp():
    """Get CPU temperature"""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return None

def get_camera_metadata():
    """Get camera sensor metadata from rpicam-vid output file"""
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
    """Read BME680 sensor with air quality calculations"""
    if not bme680:
        return {}
    try:
        # Read raw sensor values
        temperature = round(bme680.temperature, 2)
        humidity = round(bme680.humidity, 2)
        pressure = round(bme680.pressure, 2)
        gas_raw = round(bme680.gas, 2)
        altitude = round(bme680.altitude, 2)

        # Calculate compensated gas resistance
        gas_compensated = calculate_gas_resistance_compensated(gas_raw, humidity)

        # Calculate IAQ
        iaq = calculate_iaq(gas_raw, humidity)
        iaq_classification = get_iaq_classification(iaq)
        co2_equivalent = estimate_co2_equivalent(iaq)

        return {
            'bme680': {
                'temperature': temperature,
                'humidity': humidity,
                'pressure': pressure,
                'gas_raw': gas_raw,  # Raw gas resistance in Ω
                'gas_compensated': round(gas_compensated, 3) if gas_compensated else None,
                'iaq': iaq,  # Indoor Air Quality index (0-500)
                'iaq_classification': iaq_classification,  # Text classification
                'co2_equivalent': co2_equivalent,  # Estimated CO2 in ppm
                'altitude': altitude,
                'calibration_status': 'calibrated' if bme680_baseline['gas_baseline'] else 'calibrating',
                'calibration_progress': min(100, int((bme680_baseline['samples_collected'] / 900) * 100))
            }
        }
    except Exception as e:
        print(f"Error reading BME680: {e}")
        return {}

def get_system_stats():
    """Get system statistics"""
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

def init_mqtt():
    """Initialize MQTT client connection"""
    global mqtt_client
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"✓ Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        return True
    except Exception as e:
        print(f"✗ MQTT connection failed: {e}")
        return False

def publish_mqtt_data():
    """Publish sensor data to MQTT"""
    if not mqtt_client:
        return

    timestamp = int(time.time())

    try:
        # BME680 sensor data
        i2c_data = sensor_data.get('i2c_sensors', {}).get('bme680', {})
        if i2c_data:
            mqtt_client.publish("beeper/sensors/bme680/temperature",
                              json.dumps({"value": i2c_data.get('temperature'), "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/humidity",
                              json.dumps({"value": i2c_data.get('humidity'), "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/pressure",
                              json.dumps({"value": i2c_data.get('pressure'), "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/gas_raw",
                              json.dumps({"value": i2c_data.get('gas_raw'), "timestamp": timestamp}))

            # New air quality metrics
            if i2c_data.get('gas_compensated') is not None:
                mqtt_client.publish("beeper/sensors/bme680/gas_compensated",
                                  json.dumps({"value": i2c_data.get('gas_compensated'), "timestamp": timestamp}))
            if i2c_data.get('iaq') is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq",
                                  json.dumps({"value": i2c_data.get('iaq'), "timestamp": timestamp}))
            if i2c_data.get('co2_equivalent') is not None:
                mqtt_client.publish("beeper/sensors/bme680/co2_equivalent",
                                  json.dumps({"value": i2c_data.get('co2_equivalent'), "timestamp": timestamp}))

        # CPU temperature
        if sensor_data.get('cpu_temp'):
            mqtt_client.publish("beeper/sensors/cpu/temperature",
                              json.dumps({"value": sensor_data['cpu_temp'], "timestamp": timestamp}))

        # Camera sensor data
        camera_data = sensor_data.get('camera', {})
        if camera_data:
            if camera_data.get('exposure_time'):
                mqtt_client.publish("beeper/sensors/camera/exposure_time",
                                  json.dumps({"value": camera_data['exposure_time'], "timestamp": timestamp}))
            if camera_data.get('analogue_gain'):
                mqtt_client.publish("beeper/sensors/camera/analogue_gain",
                                  json.dumps({"value": camera_data['analogue_gain'], "timestamp": timestamp}))
            if camera_data.get('lux'):
                mqtt_client.publish("beeper/sensors/camera/lux",
                                  json.dumps({"value": camera_data['lux'], "timestamp": timestamp}))
            if camera_data.get('color_temperature'):
                mqtt_client.publish("beeper/sensors/camera/color_temperature",
                                  json.dumps({"value": camera_data['color_temperature'], "timestamp": timestamp}))

        # System stats
        sys_data = sensor_data.get('system', {})
        if sys_data:
            mqtt_client.publish("beeper/system/cpu_percent",
                              json.dumps({"value": sys_data.get('cpu_percent'), "timestamp": timestamp}))
            mqtt_client.publish("beeper/system/memory_percent",
                              json.dumps({"value": sys_data.get('memory_percent'), "timestamp": timestamp}))
            mqtt_client.publish("beeper/system/disk_percent",
                              json.dumps({"value": sys_data.get('disk_percent'), "timestamp": timestamp}))
    except Exception as e:
        print(f"✗ MQTT publish error: {e}")

def update_sensor_data():
    """Update all sensor data (background thread)"""
    while True:
        try:
            sensor_data['cpu_temp'] = get_cpu_temp()
            sensor_data['camera'] = get_camera_metadata()
            sensor_data['system'] = get_system_stats()
            sensor_data['i2c_sensors'] = get_i2c_sensor_data()
            sensor_data['last_update'] = time.time()

            # Publish to MQTT every 10 seconds
            if int(time.time()) % 10 == 0:
                publish_mqtt_data()
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
        
        /* Scattered chicken background - different sizes and rotations */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.15;
            z-index: 0;
            pointer-events: none;
            background-image:
                /* Top row - scattered chickens */
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                /* Middle rows - more scattered chickens */
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                /* Bottom rows - scattered chickens */
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image');
            background-size:
                80px, 120px, 60px, 100px,
                90px, 70px, 110px, 85px,
                75px, 95px, 65px, 105px,
                88px, 72px, 115px, 68px,
                82px, 98px, 78px, 92px;
            background-position:
                8% 12%, 28% 8%, 52% 15%, 78% 10%,
                15% 32%, 42% 28%, 68% 35%, 88% 30%,
                12% 52%, 38% 48%, 62% 55%, 85% 50%,
                18% 72%, 48% 68%, 72% 75%, 92% 70%,
                25% 88%, 55% 85%, 80% 90%, 95% 88%;
            background-repeat: no-repeat;
        }

        body::after {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.12;
            z-index: 0;
            pointer-events: none;
            background-image:
                /* More scattered chickens with rotations (via different positioning) */
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image'),
                url('/chicken_image'), url('/chicken_image'), url('/chicken_image'), url('/chicken_image');
            background-size:
                110px, 65px, 95px, 85px,
                102px, 78px, 88px, 73px,
                92px, 70px, 108px, 83px,
                76px, 98px, 87px, 105px;
            background-position:
                18% 18%, 45% 12%, 72% 20%, 95% 15%,
                5% 42%, 32% 38%, 58% 45%, 82% 40%,
                22% 62%, 50% 58%, 75% 65%, 98% 60%,
                10% 82%, 40% 78%, 65% 85%, 88% 80%;
            background-repeat: no-repeat;
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
        <!-- Audio button removed - audio always enabled -->
    </div>
    
    <div class="video-grid dual" id="videoGrid">
        <div class="video-container" id="csiContainer">
            <div class="video-label">IR CAMERA (CSI)</div>
            <iframe id="csiFrame" src="/csi_camera"></iframe>
        </div>
        <div class="video-container" id="usbContainer">
            <div class="video-label">USB WEBCAM</div>
            <iframe id="usbFrame" src="/usb_camera"></iframe>
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
                        // Determine IAQ status color
                        let iaq_class = 'status-good';
                        if (env.iaq !== null && env.iaq !== undefined) {
                            if (env.iaq > 250) iaq_class = 'status-error';
                            else if (env.iaq > 150) iaq_class = 'status-warn';
                        }

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
                        `;

                        // Show calibration status or air quality data
                        if (env.calibration_status === 'calibrating') {
                            envHtml += `
                                <div class="metric">
                                    <span class="metric-label">IAQ Status</span>
                                    <span class="metric-value status-warn">Calibrating ${env.calibration_progress}%</span>
                                </div>
                                <div class="metric">
                                    <span class="metric-label">Gas (Raw)</span>
                                    <span class="metric-value">${env.gas_raw} Ω</span>
                                </div>
                            `;
                        } else {
                            envHtml += `
                                <div class="metric">
                                    <span class="metric-label">Air Quality (IAQ)</span>
                                    <span class="metric-value ${iaq_class}">${env.iaq !== null ? env.iaq : 'N/A'}</span>
                                </div>
                                <div class="metric">
                                    <span class="metric-label">IAQ Level</span>
                                    <span class="metric-value ${iaq_class}">${env.iaq_classification}</span>
                                </div>
                                <div class="metric">
                                    <span class="metric-label">CO₂ Equiv.</span>
                                    <span class="metric-value">${env.co2_equivalent !== null ? env.co2_equivalent + ' ppm' : 'N/A'}</span>
                                </div>
                                <div class="metric">
                                    <span class="metric-label">Gas (Raw)</span>
                                    <span class="metric-value">${env.gas_raw} Ω</span>
                                </div>
                            `;
                        }
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

        // Auto-unmute USB camera after autoplay starts
        const usbFrame = document.getElementById("usbFrame");

        function attemptUnmute() {
            try {
                const iframeDoc = usbFrame.contentDocument || usbFrame.contentWindow.document;
                const video = iframeDoc.querySelector("video");
                if (video) {
                    // Check if video is already playing
                    if (!video.paused && !video.ended && video.readyState > 2) {
                        video.muted = false;
                        video.volume = 1.0;
                        console.log("USB camera audio unmuted (already playing)");
                    }

                    // Also listen for playing event in case it hasn't started yet
                    video.addEventListener("playing", function() {
                        video.muted = false;
                        video.volume = 1.0;
                        console.log("USB camera audio unmuted (on playing event)");
                    });
                }
            } catch(e) {
                console.log("Could not access iframe content (cross-origin)", e);
            }
        }

        // Try to unmute after iframe loads
        usbFrame.addEventListener("load", function() {
            setTimeout(attemptUnmute, 1000);
            // Try again after 3 seconds in case video wasn't ready
            setTimeout(attemptUnmute, 3000);
        });
    </script>
</body>
</html>
    ''')

# ============= MAIN =============

if __name__ == '__main__':
    print("\n=== BEEPER KEEPER 10000 - Dual Camera System ===\n")

    # Initialize sensors
    init_i2c_sensors()

    # Initialize MQTT
    init_mqtt()

    # Start background data collection
    sensor_thread = threading.Thread(target=update_sensor_data, daemon=True)
    sensor_thread.start()

    print("\n✓ Monitoring server starting on http://0.0.0.0:8080")
    print("  IR Camera: /csi_camera")
    print("  USB Camera: /usb_camera")
    print("  Web UI: http://172.16.0.28:8080\n")

    app.run(host='0.0.0.0', port=8080, threaded=True)
