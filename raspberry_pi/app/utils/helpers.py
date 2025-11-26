"""
Helper Utilities

Common helper functions for data formatting and system info.
"""
import psutil


def get_cpu_temp():
    """Read CPU temperature from thermal zone"""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return None


def get_system_stats():
    """Get system statistics"""
    try:
        return {
            'cpu_percent': round(psutil.cpu_percent(interval=0.1), 1),
            'memory_percent': round(psutil.virtual_memory().percent, 1),
            'disk_percent': round(psutil.disk_usage('/').percent, 1),
            'uptime_seconds': int(psutil.time.time() - psutil.boot_time())
        }
    except:
        return {}


def format_bme680_data(data):
    """Format BME680 sensor data for display with BSEC calibration status"""
    if not data:
        return {}

    # BSEC accuracy: 0=stabilizing, 1=low, 2=medium, 3=high (calibrated)
    iaq_accuracy = data.get('iaq_accuracy', 0)

    # Map accuracy to calibration status
    calibrating = iaq_accuracy < 3

    # Get calibration progress from MQTT data (calculated by mqtt_publisher using BSEC)
    calibration_progress = data.get('calibration_progress', 0) or 0

    # Calculate calibration day from progress (0-100% over 4 days)
    if calibration_progress < 25:
        calibration_day = 1
        calibration_day_label = f"Day 1 of 4 ({calibration_progress:.1f}%)"
    elif calibration_progress < 50:
        calibration_day = 2
        calibration_day_label = f"Day 2 of 4 ({calibration_progress:.1f}%)"
    elif calibration_progress < 75:
        calibration_day = 3
        calibration_day_label = f"Day 3 of 4 ({calibration_progress:.1f}%)"
    elif calibration_progress < 100:
        calibration_day = 4
        calibration_day_label = f"Day 4 of 4 ({calibration_progress:.1f}%)"
    else:
        calibration_day = 4
        calibration_day_label = "Calibrated"

    # Base sensor readings
    result = {
        'temperature': round(data.get('temperature', 0), 1),
        'humidity': round(data.get('humidity', 0), 1),
        'pressure': round(data.get('pressure', 0), 1),
        'gas_raw': int(data.get('gas_raw', 0)),
        'iaq_accuracy': iaq_accuracy,
        'calibration_progress': calibration_progress,
        'calibration_day': calibration_day,
        'calibration_day_label': calibration_day_label
    }

    if calibrating:
        result['calibration_status'] = 'calibrating'
    else:
        result['calibration_status'] = 'ready'

        # Classify IAQ level
        iaq = data.get('iaq', 0)
        if iaq <= 50:
            iaq_class = 'Excellent'
        elif iaq <= 100:
            iaq_class = 'Good'
        elif iaq <= 150:
            iaq_class = 'Moderate'
        elif iaq <= 200:
            iaq_class = 'Poor'
        elif iaq <= 300:
            iaq_class = 'Very Poor'
        else:
            iaq_class = 'Severe'

        result.update({
            'iaq': round(data.get('iaq', 0), 1),
            'iaq_class': iaq_class,
            'co2_equivalent': round(data.get('co2_equivalent', 0), 0)
        })

    return result


def format_camera_metadata(data):
    """Format camera metadata for display (CSI camera sensor data)"""
    if not data:
        return {}

    # Transform PascalCase MQTT keys to snake_case for frontend
    return {
        'exposure_time': data.get('ExposureTime'),
        'analogue_gain': round(data.get('AnalogueGain', 0), 1),
        'lux': round(data.get('Lux', 0), 1) if data.get('Lux') is not None else None,
        'colour_temp': data.get('ColourTemperature'),
        'frame_duration': data.get('FrameDuration'),
        'digital_gain': data.get('DigitalGain')
    }
