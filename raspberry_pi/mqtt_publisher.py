#!/usr/bin/env python3
"""
BEEPER KEEPER 10000 - MQTT Publisher
=====================================

Publishes sensor data from Raspberry Pi to MQTT broker for Grafana visualization.

Publishes:
- BME680 environmental data (temperature, humidity, pressure, gas resistance, IAQ, CO2)
- CPU temperature
- System stats (CPU%, memory%, disk%)
- Camera metadata (if available)
- Audio levels (if USB microphone detected)

MQTT Topics:
- beeper/sensors/bme680/all (includes IAQ and CO2 equivalent)
- beeper/sensors/cpu/temperature
- beeper/system/cpu_percent
- beeper/system/memory_percent
- beeper/system/disk_percent
- beeper/camera/csi/metadata
- beeper/audio/level (basic dB reading)
- beeper/audio/frequency/all (FFT analysis: peak frequency, spectral centroid, band energies)
- beeper/audio/stats/all (rolling averages, peak, standard deviation)
- beeper/audio/events/activity_state (detected activity state: quiet/active/alarmed/distress)

Dependencies:
- paho-mqtt
- psutil
- adafruit-circuitpython-bme680 (optional, for BME680 sensor)
- sounddevice, numpy (optional, for audio monitoring)

Install: pip3 install paho-mqtt psutil adafruit-circuitpython-bme680 sounddevice numpy

Environment Variables:
- MQTT_BROKER_HOST: MQTT broker hostname/IP (default: localhost)
- MQTT_BROKER_PORT: MQTT broker port (default: 1883)

Author: z3r0-c001
License: MIT
"""

import paho.mqtt.client as mqtt
import time
import json
import psutil
from datetime import datetime, time as dtime
import os
import math
import numpy as np
import pytz
import threading

# Audio sample rate constant (shared by capture and FFT analysis)
AUDIO_SAMPLE_RATE = 48000  # USB webcam microphone sample rate

# Load configuration
try:
    from config import *
except ImportError:
    print("WARNING: config.py not found. Using default configuration.")
    MQTT_BROKER = os.environ.get('MQTT_BROKER_HOST', 'localhost')
    MQTT_PORT = int(os.environ.get('MQTT_BROKER_PORT', 1883))
    MQTT_CLIENT_ID = "beeper_publisher"
    BME680_ENABLED = True
    BME680_I2C_ADDRESS = 0x76
    PUBLISH_INTERVAL_SECONDS = 10

# Initialize MQTT client
mqtt_client = None
bme680 = None
audio_stream = None
audio_enabled = False

# Audio monitoring history (for rolling averages and event detection)
audio_history = []  # List of recent dB readings for rolling averages
AUDIO_HISTORY_SIZE = 6  # Keep last 60 seconds (6 readings at 10s intervals)

# ML Feed Level globals (async execution to prevent blocking)
ml_feed_data = None  # Cached ML prediction result
ml_feed_lock = threading.Lock()  # Thread safety for shared data
ml_feed_thread = None  # Background thread handle
ml_last_update = 0  # Timestamp of last ML update
ML_UPDATE_INTERVAL = 300  # Run ML prediction every 5 minutes (300s) - TFLite loading is slow on Pi3

# BSEC state and calibration directories
BME680_BASELINE_DIR = '/var/lib/beeperKeeper'

# BSEC Calibration Start Time Tracking (for UI progress display)
BSEC_CAL_START_FILE = os.path.join(BME680_BASELINE_DIR, 'bsec_calibration_start.txt')
BSEC_CAL_START_FALLBACK = '/tmp/bsec_calibration_start.txt'

# Cache for BSEC data (used to merge with Adafruit readings)
bsec_cache = {
    'iaq': None,
    'iaq_accuracy': 0,
    'co2_equivalent': None,
    'breath_voc_equivalent': None,
    'static_iaq': None,
    'timestamp': 0
}

# Weather data cache and settings (NWS API - free, no key required)
weather_cache = {
    'current': None,
    'forecast': None,
    'last_update': 0
}
WEATHER_UPDATE_INTERVAL = 1800  # Update weather every 30 minutes
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/GYX/11,13/forecast"
NWS_USER_AGENT = "BeeperKeeper/2.0 (chicken coop monitor)"


def fetch_weather():
    """Fetch weather data from National Weather Service API."""
    global weather_cache

    try:
        import urllib.request
        import urllib.error

        # Check if we need to update
        if time.time() - weather_cache['last_update'] < WEATHER_UPDATE_INTERVAL:
            return weather_cache  # Return cached data

        print("🌤️  Fetching weather data from NWS...")

        # Create request with required User-Agent header
        req = urllib.request.Request(
            NWS_FORECAST_URL,
            headers={'User-Agent': NWS_USER_AGENT, 'Accept': 'application/geo+json'}
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        periods = data.get('properties', {}).get('periods', [])

        if not periods:
            print("⚠️  No forecast periods in NWS response")
            return weather_cache

        # Current conditions (first period)
        current = periods[0]
        current_data = {
            'temperature': current.get('temperature'),
            'temperatureUnit': current.get('temperatureUnit', 'F'),
            'shortForecast': current.get('shortForecast', ''),
            'detailedForecast': current.get('detailedForecast', ''),
            'windSpeed': current.get('windSpeed', ''),
            'windDirection': current.get('windDirection', ''),
            'isDaytime': current.get('isDaytime', True),
            'icon': current.get('icon', ''),
            'name': current.get('name', '')
        }

        # 5-day forecast (next 10 periods = 5 days of day/night)
        forecast_data = []
        for period in periods[:10]:
            forecast_data.append({
                'name': period.get('name', ''),
                'temperature': period.get('temperature'),
                'temperatureUnit': period.get('temperatureUnit', 'F'),
                'shortForecast': period.get('shortForecast', ''),
                'isDaytime': period.get('isDaytime', True),
                'icon': period.get('icon', '')
            })

        # Update cache
        weather_cache = {
            'current': current_data,
            'forecast': forecast_data,
            'last_update': time.time()
        }

        print(f"✓ Weather: {current_data['temperature']}°{current_data['temperatureUnit']} - {current_data['shortForecast']}")
        return weather_cache

    except urllib.error.URLError as e:
        print(f"⚠️  Weather fetch failed (network): {e}")
        return weather_cache
    except Exception as e:
        print(f"⚠️  Weather fetch error: {e}")
        return weather_cache


def publish_weather():
    """Publish weather data to MQTT."""
    weather = fetch_weather()

    if weather['current']:
        # Publish current conditions
        mqtt_client.publish("beeper/weather/current", json.dumps(weather['current']))

        # Publish forecast
        if weather['forecast']:
            mqtt_client.publish("beeper/weather/forecast", json.dumps(weather['forecast']))

        # Publish combined for easy frontend consumption
        mqtt_client.publish("beeper/weather/all", json.dumps({
            'current': weather['current'],
            'forecast': weather['forecast'],
            'timestamp': int(time.time())
        }))


def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the MQTT broker."""
    if rc == 0:
        print(f"✓ Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"✗ Failed to connect to MQTT broker. Return code: {rc}")

def on_publish(client, userdata, mid):
    """Callback for when a message is published."""
    pass  # Uncomment for debugging: print(f"Message {mid} published")

def init_mqtt():
    """
    Initialize MQTT client connection with retry logic.

    Implements exponential backoff with max 5 retries:
    - Initial delay: 2s
    - Max delay: 30s
    - Only exits after all retries exhausted
    """
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_publish = on_publish

    max_retries = 5
    retry_delay = 2  # Initial delay in seconds
    max_delay = 30   # Maximum delay between retries

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Attempting MQTT connection to {MQTT_BROKER}:{MQTT_PORT} (attempt {attempt}/{max_retries})...")
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
            # Give the connection a moment to establish
            time.sleep(1)
            return True
        except Exception as e:
            if attempt < max_retries:
                print(f"✗ MQTT connection failed: {e}")
                print(f"  Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # Exponential backoff with cap
                retry_delay = min(retry_delay * 2, max_delay)
            else:
                print(f"✗ MQTT connection failed after {max_retries} attempts: {e}")
                print(f"  Final error: Unable to connect to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
                return False

    return False

def init_bme680():
    """Initialize BME680 environmental sensor."""
    global bme680
    if not BME680_ENABLED:
        print("ℹ BME680 sensor disabled in configuration")
        return False

    try:
        import board
        import busio
        import adafruit_bme680
        i2c = busio.I2C(board.SCL, board.SDA)

        try:
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=BME680_I2C_ADDRESS)
            print(f"✓ BME680 sensor detected at 0x{BME680_I2C_ADDRESS:02x}")
            print("  Using BSEC for IAQ/CO2 calculations (vendor algorithm)")
            return True
        except:
            # Try alternate address
            alt_address = 0x77 if BME680_I2C_ADDRESS == 0x76 else 0x76
            bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=alt_address)
            print(f"✓ BME680 sensor detected at 0x{alt_address:02x}")
            return True
    except Exception as e:
        print(f"✗ BME680 initialization failed: {e}")
        return False

def save_bsec_calibration_start():
    """
    Save BSEC calibration start timestamp to file (only if doesn't exist yet).
    This tracks when the 4-day BSEC calibration period began.
    """
    global BSEC_CAL_START_FILE

    # Check if file already exists - don't overwrite existing calibration timestamp
    if os.path.exists(BSEC_CAL_START_FILE):
        try:
            with open(BSEC_CAL_START_FILE, 'r') as f:
                timestamp = float(f.read().strip())
                elapsed_hours = (time.time() - timestamp) / 3600.0
                print(f"✓ BSEC calibration in progress: {elapsed_hours:.1f} hours elapsed")
                return True
        except:
            pass  # File exists but corrupted, will recreate

    # File doesn't exist, create it with current timestamp
    try:
        # Try to create directory if it doesn't exist
        if not os.path.exists(BME680_BASELINE_DIR):
            os.makedirs(BME680_BASELINE_DIR, mode=0o755, exist_ok=True)

        with open(BSEC_CAL_START_FILE, 'w') as f:
            f.write(str(int(time.time())))
        print(f"✓ BSEC calibration start time saved to {BSEC_CAL_START_FILE}")
        return True
    except PermissionError:
        # Fallback to /tmp if no permissions
        print(f"⚠ No permission to write {BSEC_CAL_START_FILE}, using fallback")
        BSEC_CAL_START_FILE = BSEC_CAL_START_FALLBACK
        try:
            with open(BSEC_CAL_START_FILE, 'w') as f:
                f.write(str(int(time.time())))
            print(f"✓ BSEC calibration start time saved to fallback: {BSEC_CAL_START_FILE}")
            return True
        except Exception as e:
            print(f"✗ Could not save BSEC calibration start time to fallback: {e}")
    except Exception as e:
        print(f"✗ Could not save BSEC calibration start time: {e}")
    return False

def load_bsec_calibration_start():
    """
    Load BSEC calibration start timestamp from file.
    Returns timestamp (float) or None if not found.
    """
    global BSEC_CAL_START_FILE

    try:
        if os.path.exists(BSEC_CAL_START_FILE):
            with open(BSEC_CAL_START_FILE, 'r') as f:
                return float(f.read().strip())
    except PermissionError:
        # Try fallback location
        BSEC_CAL_START_FILE = BSEC_CAL_START_FALLBACK
        try:
            if os.path.exists(BSEC_CAL_START_FILE):
                with open(BSEC_CAL_START_FILE, 'r') as f:
                    return float(f.read().strip())
        except:
            pass
    except:
        pass

    return None

def classify_iaq(iaq_value):
    """
    Classify IAQ value according to BSEC standard thresholds.

    BSEC IAQ Scale:
    0-50: Excellent
    51-100: Good
    101-150: Lightly polluted
    151-200: Moderately polluted
    201-250: Heavily polluted
    251-350: Severely polluted
    >350: Extremely polluted
    """
    if iaq_value is None:
        return None

    if iaq_value <= 50:
        return 'Excellent'
    elif iaq_value <= 100:
        return 'Good'
    elif iaq_value <= 150:
        return 'Moderate'
    elif iaq_value <= 200:
        return 'Poor'
    elif iaq_value <= 300:
        return 'Very Poor'
    else:
        return 'Severe'

# BSEC 2.6.1.0 Integration
# Must be initialized after function definitions but before main()
bsec_available = False
try:
    from bme680_bsec_integration import init_bsec, read_bsec
    bsec_available = init_bsec()
    if bsec_available:
        print("✓ BSEC 2.6.1.0 initialized - 4-day calibration period started")
        # Save calibration start time (only if file doesn't exist yet)
        save_bsec_calibration_start()
except Exception as e:
    print(f"⚠ BSEC 2.6.1.0 not available: {e}")

def init_audio():
    """Initialize audio input for microphone monitoring using RTSP stream analysis."""
    global audio_stream, audio_enabled
    try:
        import subprocess

        # Check if ffmpeg is available
        ffmpeg_check = subprocess.run(['which', 'ffmpeg'], capture_output=True)
        if ffmpeg_check.returncode != 0:
            print("ℹ ffmpeg command not found. Audio monitoring disabled.")
            return False

        # Enable audio without testing - we'll handle errors during actual capture
        # The USB webcam audio is already being streamed by ffmpeg to rtsp://localhost:8554/usb_camera
        audio_enabled = True
        print(f"✓ Audio monitoring enabled on USB webcam RTSP stream")
        return True
    except Exception as e:
        print(f"ℹ Audio initialization failed: {e}. Audio monitoring disabled.")
        return False

def get_audio_level():
    """
    Measure current audio level in decibels (dB) using ALSA dsnoop for shared capture.
    Returns: tuple of (dB level, audio_data array) or (None, None) if audio disabled

    Note: Uses AUDIO_SAMPLE_RATE constant (48kHz) matching the dsnoop configuration in ~/.asoundrc
    """
    if not audio_enabled:
        return None, None

    try:
        import subprocess
        import struct

        # Capture 1 second of audio from dsnoop_usb device (configured in ~/.asoundrc)
        # dsnoop allows multiple programs (ffmpeg + mqtt_publisher) to share USB webcam mic
        duration = 1
        # Use the global constant for sample rate consistency
        sample_rate = AUDIO_SAMPLE_RATE

        cmd = [
            'arecord', '-D', 'dsnoop_usb', '-d', str(duration), '-f', 'S16_LE',
            '-r', str(sample_rate), '-c', '1', '-t', 'raw'
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=3)

        if result.returncode != 0 or len(result.stdout) == 0:
            return None, None

        # Parse raw audio data (16-bit signed integers)
        audio_bytes = result.stdout
        num_samples = len(audio_bytes) // 2
        audio_data = np.array(struct.unpack(f'{num_samples}h', audio_bytes), dtype=np.float32)

        # Normalize to -1.0 to 1.0 range
        audio_data = audio_data / 32768.0

        # Calculate RMS (Root Mean Square) amplitude
        rms = np.sqrt(np.mean(audio_data**2))

        # Convert to decibels (dB SPL - Sound Pressure Level)
        # Reference: 20 micropascals (threshold of human hearing)
        # Logitech C270 USB microphone: ~-42 dBV/Pa sensitivity
        # Calibration for natural dB SPL readings
        if rms > 0:
            # Convert RMS to dB relative to full scale
            db_fs = 20 * np.log10(rms)

            # Calibrate to dB SPL scale
            # Logitech C270 USB microphone: ~-42 dBV/Pa sensitivity
            # Quiet room: 20-30 dB SPL
            # Normal conversation: 50-60 dB SPL
            # Chicken alarm: 70-85 dB SPL
            # Calibration offset: 70 dB (empirically tuned for C270)
            db_spl = db_fs + 70.0  # Calibrated for consumer USB webcam mic (Logitech C270)
            
            # Clamp to reasonable range (0-120 dB SPL)
            db_normalized = max(0.0, min(120.0, db_spl))
            
            return float(round(db_normalized, 1)), audio_data  # Return both dB and raw audio data
        else:
            return 0.0, audio_data
    except subprocess.TimeoutExpired:
        print(f"✗ Audio capture timed out")
        return None, None
    except Exception as e:
        print(f"✗ Audio level read error: {e}")
        return None, None

def analyze_audio_frequency(audio_data, sample_rate=None):
    """
    Perform FFT analysis on audio data to extract frequency information.

    Args:
        audio_data: numpy array of audio samples (normalized -1.0 to 1.0)
        sample_rate: sample rate in Hz (defaults to AUDIO_SAMPLE_RATE constant)

    Returns:
        dict with frequency analysis metrics or None on error
    """
    # Use the global constant if sample_rate not specified
    if sample_rate is None:
        sample_rate = AUDIO_SAMPLE_RATE
    try:
        # Perform FFT (Fast Fourier Transform)
        fft_data = np.fft.rfft(audio_data)
        fft_magnitude = np.abs(fft_data)
        fft_freqs = np.fft.rfftfreq(len(audio_data), 1.0/sample_rate)

        # Define frequency bands (Hz)
        bands = {
            'low': (0, 500),           # Rumbling, mechanical noise
            'mid_low': (500, 2000),    # General coop noise
            'mid_high': (2000, 4000),  # Chick chirps, normal vocalizations
            'high': (4000, 8000),      # Alarm calls, distress chirps
            'very_high': (8000, 24000) # Ultrasonic, equipment noise
        }

        # Calculate energy in each band
        band_energies = {}
        total_energy = np.sum(fft_magnitude ** 2)

        for band_name, (low_freq, high_freq) in bands.items():
            # Find indices for this frequency range
            band_indices = np.where((fft_freqs >= low_freq) & (fft_freqs < high_freq))[0]
            if len(band_indices) > 0:
                band_energy = np.sum(fft_magnitude[band_indices] ** 2)
                band_energies[band_name] = float(band_energy)
            else:
                band_energies[band_name] = 0.0

        # Calculate percentage of total energy per band
        band_percentages = {}
        if total_energy > 0:
            for band_name, energy in band_energies.items():
                band_percentages[band_name] = float((energy / total_energy) * 100)
        else:
            for band_name in band_energies:
                band_percentages[band_name] = 0.0

        # Find peak frequency (dominant frequency)
        peak_idx = np.argmax(fft_magnitude)
        peak_frequency = float(fft_freqs[peak_idx])

        # Calculate spectral centroid (weighted mean of frequencies - indicates "brightness")
        if total_energy > 0:
            spectral_centroid = float(np.sum(fft_freqs * (fft_magnitude ** 2)) / total_energy)
        else:
            spectral_centroid = 0.0

        # Calculate high-frequency ratio (alarm call indicator)
        high_energy = band_energies.get('high', 0) + band_energies.get('very_high', 0)
        if total_energy > 0:
            high_ratio = float((high_energy / total_energy) * 100)
        else:
            high_ratio = 0.0

        return {
            'band_percentages': band_percentages,
            'peak_frequency': peak_frequency,
            'spectral_centroid': spectral_centroid,
            'high_ratio': high_ratio
        }

    except Exception as e:
        print(f"✗ Frequency analysis error: {e}")
        return None

def get_audio_statistics():
    """
    Calculate statistical metrics from audio history.

    Returns:
        dict with statistical metrics or None if insufficient data
    """
    global audio_history

    if len(audio_history) < 3:  # Need at least 3 samples
        return None

    try:
        recent_values = audio_history[-6:]  # Last 60 seconds

        # Rolling averages
        avg_30s = float(np.mean(recent_values[-3:])) if len(recent_values) >= 3 else None
        avg_60s = float(np.mean(recent_values)) if len(recent_values) >= 6 else None

        # Peak in last 60 seconds
        peak_60s = float(np.max(recent_values))

        # Standard deviation (variability indicator)
        stddev = float(np.std(recent_values)) if len(recent_values) >= 3 else 0.0

        return {
            'avg_30s': avg_30s,
            'avg_60s': avg_60s,
            'peak_60s': peak_60s,
            'stddev': stddev
        }

    except Exception as e:
        print(f"✗ Audio statistics error: {e}")
        return None

def detect_audio_event(current_db, stats):
    """
    Detect audio activity state based on current level and statistics.

    Args:
        current_db: Current audio level in dB
        stats: Statistics dict from get_audio_statistics()

    Returns:
        str: Activity state - "quiet", "active", "alarmed", or "distress"
    """
    if stats is None or current_db is None:
        return "quiet"

    try:
        avg_60s = stats.get('avg_60s', current_db)

        # Thresholds based on updated alert levels
        if current_db < 35:
            return "quiet"  # Below excited threshold
        elif 35 <= current_db < 46:
            return "active"  # Normal activity (excited/communicating)
        elif 46 <= current_db < 56:
            # Check if sustained
            if avg_60s and avg_60s >= 46:
                return "alarmed"  # Sustained mild alerting
            else:
                return "active"  # Brief spike, still active
        elif current_db >= 56:
            # High alert or distress
            if avg_60s and avg_60s >= 56:
                return "distress"  # Sustained high levels
            else:
                return "alarmed"  # Brief high spike
        else:
            return "quiet"

    except Exception as e:
        print(f"✗ Event detection error: {e}")
        return "quiet"


def get_current_lights_state():
    """Determine if lights should be on or off based on Eastern Time schedule."""
    try:
        est = pytz.timezone("America/New_York")
        now = datetime.now(est)
        current_time = now.time()
        
        lights_on_time = dtime(6, 30)   # 6:30 AM
        lights_off_time = dtime(19, 0)  # 7:00 PM
        
        if lights_on_time <= current_time < lights_off_time:
            return "on"
        else:
            return "off"
    except Exception as e:
        print(f"✗ Error determining lights state: {e}")
        return None

def publish_lights_state():
    """Publish current lights state to MQTT every cycle for continuous chart data."""
    try:
        current_state = get_current_lights_state()
        
        if current_state is None:
            return
        
        est = pytz.timezone("America/New_York")
        now = datetime.now(est)
        timestamp = int(time.time())
        
        lights_data = {
            "state": current_state,
            "timestamp": timestamp,
            "local_time": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "sensor_type": "schedule",
            "location": "raspberry_pi"
        }
        
        mqtt_client.publish("beeper/lights/state", json.dumps(lights_data))
        print(f"📤 Lights: {current_state.upper()}")
        
    except Exception as e:
        print(f"✗ Lights state publish error: {e}")

def update_bsec_cache():
    """
    Read BSEC data and update cache for use by main publish_sensor_data().
    Also publishes detailed BSEC topics for advanced monitoring.
    """
    global bsec_available, bsec_cache

    if not bsec_available:
        return

    try:
        data = read_bsec()
        if data is None:
            # BSEC needs time to complete first measurement cycle
            return

        timestamp = int(time.time())

        # Update cache with BSEC values (used by publish_sensor_data for /all topic)
        bsec_cache['iaq'] = data.get('iaq')
        bsec_cache['iaq_accuracy'] = data.get('iaq_accuracy', 0)
        bsec_cache['co2_equivalent'] = data.get('co2_equivalent')
        bsec_cache['breath_voc_equivalent'] = data.get('breath_voc_equivalent')
        bsec_cache['static_iaq'] = data.get('static_iaq')
        bsec_cache['timestamp'] = timestamp

        # Calculate calibration progress for UI (BSEC needs ~96 hours for full accuracy=3)
        cal_start = load_bsec_calibration_start()
        if cal_start:
            cal_elapsed_hours = (time.time() - cal_start) / 3600.0
            # Progress: 0-96 hours = 0-100%
            bsec_cache['calibration_progress'] = min(100.0, round((cal_elapsed_hours / 96.0) * 100, 1))
        else:
            bsec_cache['calibration_progress'] = 0

        # Publish detailed BSEC metrics (separate topics for advanced monitoring)
        if data.get('iaq') is not None:
            mqtt_client.publish("beeper/sensors/bme680/iaq_bsec",
                              json.dumps({"value": data['iaq'], "accuracy": data['iaq_accuracy'], "timestamp": timestamp}))

        if data.get('static_iaq') is not None:
            mqtt_client.publish("beeper/sensors/bme680/static_iaq_bsec",
                              json.dumps({"value": data['static_iaq'], "timestamp": timestamp}))

        if data.get('co2_equivalent') is not None:
            mqtt_client.publish("beeper/sensors/bme680/co2_bsec",
                              json.dumps({"value": data['co2_equivalent'], "timestamp": timestamp}))

        if data.get('breath_voc_equivalent') is not None:
            mqtt_client.publish("beeper/sensors/bme680/breath_voc_bsec",
                              json.dumps({"value": data['breath_voc_equivalent'], "timestamp": timestamp}))

        # Publish combined BSEC data (detailed topic)
        data['timestamp'] = timestamp
        data['sensor_type'] = 'bme680_bsec'
        data['location'] = 'raspberry_pi'
        mqtt_client.publish("beeper/sensors/bme680/bsec_all", json.dumps(data))

        # Log BSEC calibration status
        accuracy_stars = "★" * data['iaq_accuracy'] + "☆" * (3 - data['iaq_accuracy'])
        if data.get('iaq') is not None:
            print(f"📤 BSEC: IAQ {data['iaq']:.1f} ({accuracy_stars}), CO₂ {data['co2_equivalent']:.0f}ppm")

    except Exception as e:
        print(f"✗ BSEC read error: {e}")

def get_cpu_temp():
    """Read CPU temperature from thermal zone."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except:
        return None

def publish_sensor_data():
    """Read and publish all sensor data to MQTT."""
    timestamp = int(time.time())

    # First update BSEC cache (reads BSEC and publishes detailed topics)
    update_bsec_cache()

    # BME680 Environmental Sensor - raw readings from Adafruit + IAQ/CO2 from BSEC
    if bme680:
        try:
            # Read raw sensor values (Adafruit library for basic readings)
            temperature = round(bme680.temperature, 2)
            humidity = round(bme680.humidity, 2)
            pressure = round(bme680.pressure, 2)
            gas_raw = int(bme680.gas)

            # Get air quality metrics from BSEC cache (Bosch vendor algorithm)
            iaq = bsec_cache.get('iaq')
            co2_equivalent = bsec_cache.get('co2_equivalent')
            calibration_progress = bsec_cache.get('calibration_progress', 0)
            iaq_accuracy = bsec_cache.get('iaq_accuracy', 0)

            # Round BSEC values for consistency
            if iaq is not None:
                iaq = round(iaq, 1)
            if co2_equivalent is not None:
                co2_equivalent = round(co2_equivalent, 0)

            # Classify IAQ level using BSEC value
            iaq_classification = classify_iaq(iaq)

            # Build combined data payload (same field names for Grafana compatibility)
            data = {
                "temperature": temperature,
                "humidity": humidity,
                "pressure": pressure,
                "gas_raw": gas_raw,
                "iaq": iaq,
                "iaq_accuracy": iaq_accuracy,
                "iaq_classification": iaq_classification,
                "co2_equivalent": co2_equivalent,
                "calibration_progress": calibration_progress,
                "timestamp": timestamp,
                "sensor_type": "bme680",
                "location": "raspberry_pi"
            }

            # Publish to individual topics
            mqtt_client.publish("beeper/sensors/bme680/temperature",
                              json.dumps({"value": temperature, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/humidity",
                              json.dumps({"value": humidity, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/pressure",
                              json.dumps({"value": pressure, "timestamp": timestamp}))
            mqtt_client.publish("beeper/sensors/bme680/gas",
                              json.dumps({"value": gas_raw, "timestamp": timestamp}))

            # Publish air quality metrics (from BSEC)
            if iaq is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq",
                                  json.dumps({"value": iaq, "timestamp": timestamp}))
            if co2_equivalent is not None:
                mqtt_client.publish("beeper/sensors/bme680/co2_equivalent",
                                  json.dumps({"value": co2_equivalent, "timestamp": timestamp}))
            if iaq_classification is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq_classification",
                                  json.dumps({"value": iaq_classification, "timestamp": timestamp}))

            # Publish combined data (main topic used by Grafana)
            mqtt_client.publish("beeper/sensors/bme680/all", json.dumps(data))

            # Log sensor readings
            if iaq is not None:
                accuracy_stars = "★" * iaq_accuracy + "☆" * (3 - iaq_accuracy)
                print(f"📤 BME680: {temperature}°C, {humidity}%, {pressure}hPa | BSEC IAQ: {iaq} ({accuracy_stars}), CO₂: {co2_equivalent}ppm")
            else:
                print(f"📤 BME680: {temperature}°C, {humidity}%, {pressure}hPa, Gas: {gas_raw}Ω (BSEC calibrating {calibration_progress}%)")
        except Exception as e:
            print(f"✗ BME680 read error: {e}")

    # CPU Temperature
    cpu_temp = get_cpu_temp()
    if cpu_temp:
        data = {
            "cpu_temp": cpu_temp,
            "timestamp": timestamp,
            "sensor_type": "cpu",
            "location": "raspberry_pi"
        }
        mqtt_client.publish("beeper/sensors/cpu/temperature", json.dumps(data))
        print(f"📤 CPU Temp: {cpu_temp}°C")

    # System Stats
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        system_data = {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory.percent, 1),
            "disk_percent": round(disk.percent, 1),
            "timestamp": timestamp
        }

        mqtt_client.publish("beeper/system/stats", json.dumps(system_data))
        mqtt_client.publish("beeper/system/cpu_percent",
                          json.dumps({"value": cpu_percent, "timestamp": timestamp}))
        mqtt_client.publish("beeper/system/memory_percent",
                          json.dumps({"value": memory.percent, "timestamp": timestamp}))
        mqtt_client.publish("beeper/system/disk_percent",
                          json.dumps({"value": disk.percent, "timestamp": timestamp}))

        print(f"📤 System: CPU {cpu_percent}%, RAM {memory.percent}%, Disk {disk.percent}%")
    except Exception as e:
        print(f"✗ System stats error: {e}")

    # Camera Metadata (if available)
    try:
        if os.path.exists('/tmp/camera_metadata_stream.txt'):
            with open('/tmp/camera_metadata_stream.txt', 'rb') as f:
                f.seek(0, 2)
                file_size = f.tell()
                read_size = min(5000, file_size)
                f.seek(max(0, file_size - read_size))
                tail_data = f.read().decode('utf-8', errors='ignore')

            last_brace = tail_data.rfind('}')
            if last_brace != -1:
                search_start = max(0, last_brace - 2000)
                chunk = tail_data[search_start:last_brace+1]
                first_brace = chunk.rfind('{')
                if first_brace != -1:
                    json_str = chunk[first_brace:]
                    metadata = json.loads(json_str)
                    metadata['timestamp'] = timestamp
                    mqtt_client.publish("beeper/camera/csi/metadata", json.dumps(metadata))
                    print(f"📤 Camera metadata published")
    except Exception as e:
        pass  # Camera metadata is optional

    # Lights State Tracking
    publish_lights_state()

    # Note: BSEC data is updated at start of publish_sensor_data() via update_bsec_cache()

    # Enhanced Audio Monitoring with Frequency Analysis and Event Detection
    if audio_enabled:
        try:
            global audio_history

            # Get audio level and raw data
            audio_level, raw_audio_data = get_audio_level()

            if audio_level is not None:
                # Update history for rolling averages
                audio_history.append(audio_level)
                if len(audio_history) > AUDIO_HISTORY_SIZE:
                    audio_history.pop(0)  # Remove oldest

                # Publish basic audio level (existing topic)
                level_data = {
                    "level_db": audio_level,
                    "timestamp": timestamp,
                    "sensor_type": "microphone",
                    "location": "raspberry_pi"
                }
                mqtt_client.publish("beeper/audio/level", json.dumps(level_data))
                print(f"📤 Audio: {audio_level} dB", end="")

                # Get statistics (rolling averages, peak, stddev)
                stats = get_audio_statistics()
                if stats:
                    # Publish statistics
                    stats_data = {
                        **stats,
                        "timestamp": timestamp,
                        "sensor_type": "microphone",
                        "location": "raspberry_pi"
                    }
                    mqtt_client.publish("beeper/audio/stats/all", json.dumps(stats_data))
                    print(f" | 60s avg: {stats['avg_60s']:.1f} dB" if stats.get('avg_60s') else "", end="")

                # Detect activity state
                activity_state = detect_audio_event(audio_level, stats)
                event_data = {
                    "activity_state": activity_state,
                    "timestamp": timestamp,
                    "sensor_type": "microphone",
                    "location": "raspberry_pi"
                }
                mqtt_client.publish("beeper/audio/events/activity_state", json.dumps(event_data))
                print(f" | State: {activity_state}", end="")

                # Perform frequency analysis (if we have raw audio data)
                if raw_audio_data is not None and len(raw_audio_data) > 0:
                    # analyze_audio_frequency() will use AUDIO_SAMPLE_RATE constant
                    freq_analysis = analyze_audio_frequency(raw_audio_data)
                    if freq_analysis:
                        # Publish frequency analysis
                        freq_data = {
                            **freq_analysis,
                            "timestamp": timestamp,
                            "sensor_type": "microphone",
                            "location": "raspberry_pi"
                        }
                        mqtt_client.publish("beeper/audio/frequency/all", json.dumps(freq_data))

                        # Print frequency info
                        peak_freq = freq_analysis.get('peak_frequency', 0)
                        high_ratio = freq_analysis.get('high_ratio', 0)
                        print(f" | Peak: {peak_freq:.0f} Hz | High: {high_ratio:.1f}%")
                    else:
                        print()  # New line if no frequency data
                else:
                    print()  # New line

        except Exception as e:
            print(f"✗ Audio monitoring error: {e}")

    # ML Feed Level Monitoring (async - non-blocking)
    # Publish cached ML result immediately
    publish_feed_level_cached()
    # Start background update if needed
    schedule_ml_update()

    # Weather Data (updated every 30 minutes, cached)
    publish_weather()


def get_ml_feed_level():
    """Get feed level prediction from ML model"""
    try:
        import subprocess
        roi_image = '/tmp/test_roi_from_api.jpg'

        if not os.path.exists(roi_image):
            return None

        # Call ML wrapper script (TFLite version for faster inference)
        # Set environment variable to suppress TFLite info messages
        env = os.environ.copy()
        env['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Suppress INFO and WARNING

        result = subprocess.run(
            ['/opt/beeperKeeper/ml_predict_wrapper_tflite.sh', roi_image],
            capture_output=True,
            text=True,
            timeout=45,  # Pi3 needs ~13s for TF init + ~2-3s for inference
            env=env
        )

        if result.returncode == 0:
            # Parse JSON output
            prediction = json.loads(result.stdout.strip())
            percent = round(prediction['percent_full'], 2)
            # Derive level from percentage
            if percent >= 75:
                level = 'FULL'
            elif percent >= 50:
                level = 'MEDIUM'
            elif percent >= 25:
                level = 'LOW'
            else:
                level = 'EMPTY'
            return {
                'percent_full': percent,
                'confidence': round(prediction['confidence'], 2),
                'method': 'ml',
                'level': level
            }
        else:
            print(f"ML prediction failed: {result.stderr}")
            return None

    except Exception as e:
        print(f"ML feed level error: {e}")
        return None


def publish_feed_level_cached():
    """Publish cached ML-based feed level to MQTT (non-blocking)"""
    global ml_feed_data

    # Read cached data with thread safety
    with ml_feed_lock:
        feed_data = ml_feed_data

    try:
        if feed_data:
            mqtt_client.publish("beeper/feed/level/current", feed_data['percent_full'])
            mqtt_client.publish("beeper/feed/level/confidence", feed_data['confidence'])

            # Publish combined payload
            payload = json.dumps(feed_data)
            mqtt_client.publish("beeper/feed/level/all", payload)

            print(f"📊 Feed Level: {feed_data['percent_full']}% (confidence: {feed_data['confidence']}%)")
        else:
            print("⚠️  Feed level: ML prediction unavailable (no cache)")

    except Exception as e:
        print(f"✗ Feed level publish error: {e}")


def update_ml_feed_background():
    """Background thread function to update ML feed prediction"""
    global ml_feed_data, ml_last_update

    print("🔄 Updating ML feed level (background)...")
    feed_data = get_ml_feed_level()

    # Update cached data with thread safety
    with ml_feed_lock:
        ml_feed_data = feed_data
        ml_last_update = time.time()

    if feed_data:
        print(f"✓ ML update complete: {feed_data['percent_full']}% ({feed_data['confidence']}% confidence)")
    else:
        print("⚠️  ML update failed")


def schedule_ml_update():
    """Start ML update in background thread if needed"""
    global ml_feed_thread, ml_last_update

    current_time = time.time()

    # Check if update is needed
    if current_time - ml_last_update < ML_UPDATE_INTERVAL:
        return  # Too soon for another update

    # Check if thread is already running
    if ml_feed_thread and ml_feed_thread.is_alive():
        return  # Update already in progress

    # Start new background thread
    ml_feed_thread = threading.Thread(target=update_ml_feed_background, daemon=True)
    ml_feed_thread.start()


def main():
    """Main loop for MQTT publisher."""
    print("🐔 BEEPER KEEPER 10000 - MQTT Publisher")
    print("=" * 50)

    # Initialize MQTT
    if not init_mqtt():
        print("✗ Failed to initialize MQTT. Exiting.")
        return

    # Initialize BME680
    init_bme680()

    # Initialize Audio Monitoring
    init_audio()

    # Wait for MQTT connection
    time.sleep(2)

    print(f"\n📡 Publishing sensor data every {PUBLISH_INTERVAL_SECONDS} seconds")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            publish_sensor_data()
            print()  # Blank line between updates
            time.sleep(PUBLISH_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down MQTT publisher...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("✓ Disconnected from MQTT broker")

if __name__ == "__main__":
    main()
