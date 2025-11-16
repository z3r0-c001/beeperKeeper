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

Author: your_github_username
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

# BME680 Air Quality Configuration
# Baseline stored in /var/lib for persistence, with fallback to /tmp if permissions fail
BME680_BASELINE_DIR = '/var/lib/beeperKeeper'
BME680_BASELINE_FILE = os.path.join(BME680_BASELINE_DIR, 'bme680_baseline.json')
BME680_BASELINE_FALLBACK = '/tmp/bme680_baseline.json'

bme680_baseline = {
    'gas_baseline': None,
    'hum_baseline': 40.0,
    'calibration_time': None,
    'samples_collected': 0
}

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
            # Load baseline calibration
            load_bme680_baseline()
            if bme680_baseline['gas_baseline'] is None:
                print("⚠ BME680: No baseline found. Starting 30-minute calibration...")
            else:
                print(f"✓ BME680: Baseline loaded - Gas: {bme680_baseline['gas_baseline']:.0f}Ω")
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

def load_bme680_baseline():
    """
    Load BME680 baseline calibration from file.

    Attempts to load from /var/lib/beeperKeeper/ first, falls back to /tmp if not found.
    Creates the /var/lib directory if it doesn't exist (with appropriate permissions).
    """
    global bme680_baseline, BME680_BASELINE_FILE

    # Try to create the /var/lib directory if it doesn't exist
    try:
        if not os.path.exists(BME680_BASELINE_DIR):
            os.makedirs(BME680_BASELINE_DIR, mode=0o755, exist_ok=True)
            print(f"✓ Created baseline directory: {BME680_BASELINE_DIR}")
    except PermissionError:
        print(f"⚠ No permission to create {BME680_BASELINE_DIR}, using fallback location")
        BME680_BASELINE_FILE = BME680_BASELINE_FALLBACK
    except Exception as e:
        print(f"⚠ Could not create baseline directory: {e}, using fallback")
        BME680_BASELINE_FILE = BME680_BASELINE_FALLBACK

    # Try to load from primary location
    try:
        if os.path.exists(BME680_BASELINE_FILE):
            with open(BME680_BASELINE_FILE, 'r') as f:
                saved_baseline = json.load(f)
                bme680_baseline.update(saved_baseline)
                print(f"✓ Loaded baseline from {BME680_BASELINE_FILE}")
                return True
    except PermissionError:
        print(f"⚠ No permission to read {BME680_BASELINE_FILE}, trying fallback")
        BME680_BASELINE_FILE = BME680_BASELINE_FALLBACK
        try:
            if os.path.exists(BME680_BASELINE_FILE):
                with open(BME680_BASELINE_FILE, 'r') as f:
                    saved_baseline = json.load(f)
                    bme680_baseline.update(saved_baseline)
                    print(f"✓ Loaded baseline from fallback: {BME680_BASELINE_FILE}")
                    return True
        except Exception as e:
            print(f"⚠ Could not load BME680 baseline from fallback: {e}")
    except Exception as e:
        print(f"⚠ Could not load BME680 baseline: {e}")

    return False

def save_bme680_baseline():
    """
    Save BME680 baseline calibration to file.

    Attempts to save to /var/lib/beeperKeeper/ first, falls back to /tmp on permission error.
    """
    global BME680_BASELINE_FILE

    try:
        with open(BME680_BASELINE_FILE, 'w') as f:
            json.dump(bme680_baseline, f)
        print(f"✓ Saved baseline to {BME680_BASELINE_FILE}")
        return True
    except PermissionError:
        print(f"⚠ No permission to write {BME680_BASELINE_FILE}, trying fallback")
        BME680_BASELINE_FILE = BME680_BASELINE_FALLBACK
        try:
            with open(BME680_BASELINE_FILE, 'w') as f:
                json.dump(bme680_baseline, f)
            print(f"✓ Saved baseline to fallback: {BME680_BASELINE_FILE}")
            return True
        except Exception as e:
            print(f"✗ Could not save BME680 baseline to fallback: {e}")
    except Exception as e:
        print(f"✗ Could not save BME680 baseline: {e}")
    return False

def calculate_gas_resistance_compensated(gas_raw, humidity):
    """Calculate humidity-compensated gas resistance"""
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

    Requires 30-minute calibration period (180 samples at 10s intervals).
    Logs calibration progress every 5 minutes (30 samples) for user feedback.
    """
    global bme680_baseline

    if bme680_baseline['gas_baseline'] is None:
        if bme680_baseline['samples_collected'] < 180:  # 30 min at 10s intervals
            bme680_baseline['samples_collected'] += 1

            # Log calibration progress every 5 minutes (30 samples)
            if bme680_baseline['samples_collected'] % 30 == 0:
                elapsed_minutes = bme680_baseline['samples_collected'] // 6
                print(f"⏱ BME680 Calibration: {elapsed_minutes} of 30 minutes elapsed ({bme680_baseline['samples_collected']}/180 samples)")

            return None
        else:
            bme680_baseline['gas_baseline'] = gas_raw
            bme680_baseline['hum_baseline'] = humidity
            bme680_baseline['calibration_time'] = time.time()
            save_bme680_baseline()
            print(f"✓ BME680: Baseline calibrated! Gas={gas_raw:.0f}Ω, Hum={humidity:.1f}%")
            return 50

    gas_comp = calculate_gas_resistance_compensated(gas_raw, humidity)
    baseline_comp = calculate_gas_resistance_compensated(
        bme680_baseline['gas_baseline'],
        bme680_baseline['hum_baseline']
    )

    if baseline_comp == 0:
        return None

    gas_ratio = baseline_comp / gas_comp if gas_comp > 0 else 1.0
    iaq = 50 + (1.0 - gas_ratio) * 450
    iaq = max(0, min(500, iaq))

    return round(iaq, 1)

def estimate_co2_equivalent(iaq):
    """Estimate CO2 equivalent in ppm from IAQ"""
    if iaq is None:
        return None

    if iaq <= 50:
        co2 = 400 + (iaq / 50) * 200
    elif iaq <= 100:
        co2 = 600 + ((iaq - 50) / 50) * 200
    elif iaq <= 150:
        co2 = 800 + ((iaq - 100) / 50) * 200
    elif iaq <= 200:
        co2 = 1000 + ((iaq - 150) / 50) * 500
    elif iaq <= 300:
        co2 = 1500 + ((iaq - 200) / 100) * 1000
    else:
        co2 = 2500 + ((iaq - 300) / 200) * 2500

    return round(co2, 0)

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

    # BME680 Environmental Sensor
    if bme680:
        try:
            # Read raw sensor values
            temperature = round(bme680.temperature, 2)
            humidity = round(bme680.humidity, 2)
            pressure = round(bme680.pressure, 2)
            gas_raw = int(bme680.gas)

            # Calculate air quality metrics
            gas_compensated = calculate_gas_resistance_compensated(gas_raw, humidity)
            iaq = calculate_iaq(gas_raw, humidity)
            co2_equivalent = estimate_co2_equivalent(iaq)

            # Calculate calibration progress
            calibration_progress = 0
            if bme680_baseline['gas_baseline'] is None:
                calibration_progress = round((bme680_baseline['samples_collected'] / 180.0) * 100, 1)

            # Classify IAQ level
            iaq_classification = None
            if iaq is not None:
                if iaq <= 50:
                    iaq_classification = 'Excellent'
                elif iaq <= 100:
                    iaq_classification = 'Good'
                elif iaq <= 150:
                    iaq_classification = 'Moderate'
                elif iaq <= 200:
                    iaq_classification = 'Poor'
                elif iaq <= 300:
                    iaq_classification = 'Very Poor'
                else:
                    iaq_classification = 'Severe'

            data = {
                "temperature": temperature,
                "humidity": humidity,
                "pressure": pressure,
                "gas_raw": gas_raw,
                "gas_compensated": round(gas_compensated, 3) if gas_compensated else None,
                "iaq": iaq,
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
            mqtt_client.publish("beeper/sensors/bme680/gas_compensated",
                              json.dumps({"value": gas_compensated, "timestamp": timestamp}))

            # Publish air quality metrics
            if iaq is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq",
                                  json.dumps({"value": iaq, "timestamp": timestamp}))
            if co2_equivalent is not None:
                mqtt_client.publish("beeper/sensors/bme680/co2_equivalent",
                                  json.dumps({"value": co2_equivalent, "timestamp": timestamp}))
            if iaq_classification is not None:
                mqtt_client.publish("beeper/sensors/bme680/iaq_classification",
                                  json.dumps({"value": iaq_classification, "timestamp": timestamp}))

            # Publish combined data
            mqtt_client.publish("beeper/sensors/bme680/all", json.dumps(data))

            # Enhanced logging
            if iaq is not None:
                print(f"📤 BME680: {temperature}°C, {humidity}%, {pressure}hPa, IAQ: {iaq}, CO₂: {co2_equivalent}ppm")
            else:
                print(f"📤 BME680: {temperature}°C, {humidity}%, {pressure}hPa, Gas: {gas_raw}Ω (Calibrating {calibration_progress}%)")
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
