#!/usr/bin/env python3
"""
BEEPER KEEPER - Feed Monitor
=============================

Computer vision-based chicken feed monitoring system for glass jar feeder.
Optimized for Raspberry Pi 3B+ with OV5647 CSI camera (overhead view).

Features:
- Periodic frame capture from CSI camera RTSP stream (1920x1080 @ 5-minute intervals)
- Image quality validation (blur detection, brightness analysis)
- Glass jar detection using contour analysis and edge detection
- Feed level measurement using HSV color segmentation with top-down scanning
- MQTT publishing to existing BeeperKeeper infrastructure
- Comprehensive error handling and logging
- Lights-aware operation (only captures during lights-on hours: 6:30 AM - 7:00 PM ET)

MQTT Topics:
- beeper/feed/level/current - Current feed level with metadata
- beeper/feed/level/raw - Raw pixel measurements for debugging
- beeper/feed/alerts/status - Alert notifications for low/empty feed

Dependencies:
- opencv-python (apt: python3-opencv)
- paho-mqtt
- numpy
- pytz (for timezone support)
- rpicam-apps (for CSI camera capture)

Hardware Requirements:
- Raspberry Pi 3B+ or newer
- OV5647 CSI camera module (5MP)
- Glass jar chicken feeder
- Overhead camera mounting position

Author: z3r0-c001
License: MIT
"""

import cv2
import numpy as np
import paho.mqtt.client as mqtt
import time
import json
import os
import subprocess
from datetime import datetime
import pytz
import tensorflow as tf
from PIL import Image

# Load configuration
try:
    from feed_config import *
except ImportError:
    print("ERROR: feed_config.py not found. Please run calibrate_feed_monitor.py first.")
    exit(1)

# Global MQTT client
mqtt_client = None

# Feed level history for trend analysis
feed_history = []
FEED_HISTORY_SIZE = 4  # Keep last 4 readings (1 hour at 15min intervals)

# Last valid feed reading (retained during lights out)
last_valid_reading = None

# Timezone for lights schedule
ET = pytz.timezone('America/New_York')

# Lights schedule (6:30 AM - 7:00 PM Eastern Time)
LIGHTS_ON_HOUR = 6
LIGHTS_ON_MINUTE = 30
LIGHTS_OFF_HOUR = 19
LIGHTS_OFF_MINUTE = 0

# ML Model Configuration
TFLITE_MODEL_PATH = '/opt/beeperKeeper/models/feed_model.tflite'
ML_INPUT_SIZE = (224, 224)  # MobileNetV2 input size

# Global TFLite interpreter
tflite_interpreter = None

def get_current_lights_state():
    """
    Check if coop lights are currently ON based on time schedule.

    Lights schedule: 6:30 AM - 7:00 PM Eastern Time

    Returns:
        tuple: (lights_on: bool, current_time_et: datetime)
    """
    try:
        # Get current time in Eastern Time
        now_et = datetime.now(ET)
        current_hour = now_et.hour
        current_minute = now_et.minute

        # Convert current time and schedule to minutes for easier comparison
        current_minutes = current_hour * 60 + current_minute
        lights_on_minutes = LIGHTS_ON_HOUR * 60 + LIGHTS_ON_MINUTE
        lights_off_minutes = LIGHTS_OFF_HOUR * 60 + LIGHTS_OFF_MINUTE

        # Check if within lights-on window
        lights_on = lights_on_minutes <= current_minutes < lights_off_minutes

        return lights_on, now_et
    except Exception as e:
        print(f"✗ Error checking lights state: {e}")
        # Default to lights ON to prevent false feed readings
        return True, datetime.now()

def init_tflite_model():
    """
    Initialize TensorFlow Lite interpreter for ML-based feed level prediction.

    Returns:
        bool: True if successful, False otherwise
    """
    global tflite_interpreter

    try:
        if not os.path.exists(TFLITE_MODEL_PATH):
            print(f"✗ TFLite model not found: {TFLITE_MODEL_PATH}")
            return False

        # Load TFLite model
        tflite_interpreter = tf.lite.Interpreter(model_path=TFLITE_MODEL_PATH)
        tflite_interpreter.allocate_tensors()

        # Get input/output details
        input_details = tflite_interpreter.get_input_details()
        output_details = tflite_interpreter.get_output_details()

        print(f"✓ TFLite model loaded: {TFLITE_MODEL_PATH}")
        print(f"  Input shape: {input_details[0]['shape']}")
        print(f"  Output shape: {output_details[0]['shape']}")

        return True

    except Exception as e:
        print(f"✗ Failed to initialize TFLite model: {e}")
        return False

def predict_feed_level_ml(image):
    """
    Predict feed level using ML model (TFLite inference).

    Args:
        image: Full OpenCV BGR image (1920x1080)

    Returns:
        dict: Prediction results with percentage and confidence
              {
                  'success': bool,
                  'percentage': float,  # 0-100%
                  'confidence': float,  # 0-100% (currently fixed at 95% for ML)
                  'method': str,
                  'error': str or None
              }
    """
    global tflite_interpreter

    try:
        if tflite_interpreter is None:
            return {
                'success': False,
                'percentage': 0.0,
                'confidence': 0.0,
                'method': 'ml_tflite',
                'error': 'TFLite interpreter not initialized'
            }

        # Extract ROI from full image
        x, y, w, h = ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT
        roi = image[y:y+h, x:x+w]

        # Convert BGR to RGB
        roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)

        # Resize to 224x224 for MobileNetV2
        roi_resized = cv2.resize(roi_rgb, ML_INPUT_SIZE, interpolation=cv2.INTER_LINEAR)

        # Convert to PIL Image and back to numpy (ensures proper format)
        pil_image = Image.fromarray(roi_resized)
        img_array = np.array(pil_image, dtype=np.float32)

        # Normalize to [0, 1]
        img_array = img_array / 255.0

        # Add batch dimension: (224, 224, 3) -> (1, 224, 224, 3)
        img_array = np.expand_dims(img_array, axis=0)

        # Run inference
        input_details = tflite_interpreter.get_input_details()
        output_details = tflite_interpreter.get_output_details()

        tflite_interpreter.set_tensor(input_details[0]['index'], img_array)
        tflite_interpreter.invoke()

        # Get prediction
        prediction = tflite_interpreter.get_tensor(output_details[0]['index'])

        # Denormalize: model outputs [0, 1], convert to [0, 100]
        percentage = float(prediction[0][0] * 100.0)

        # Clamp to valid range
        percentage = max(0.0, min(100.0, percentage))

        # ML predictions are highly confident (trained to 4.80% MAE)
        confidence = 95.0

        return {
            'success': True,
            'percentage': round(percentage, 1),
            'confidence': confidence,
            'method': 'ml_tflite',
            'error': None
        }

    except Exception as e:
        return {
            'success': False,
            'percentage': 0.0,
            'confidence': 0.0,
            'method': 'ml_tflite',
            'error': str(e)
        }

def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the MQTT broker."""
    if rc == 0:
        print(f"✓ Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"✗ Failed to connect to MQTT broker. Return code: {rc}")

def init_mqtt():
    """
    Initialize MQTT client connection with retry logic.

    Implements exponential backoff with max 5 retries:
    - Initial delay: 2s
    - Max delay: 30s
    """
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    mqtt_client.on_connect = on_connect

    max_retries = 5
    retry_delay = 2
    max_delay = 30

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Attempting MQTT connection to {MQTT_BROKER}:{MQTT_PORT} (attempt {attempt}/{max_retries})...")
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
            time.sleep(1)
            return True
        except Exception as e:
            if attempt < max_retries:
                print(f"✗ MQTT connection failed: {e}")
                print(f"  Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)
            else:
                print(f"✗ MQTT connection failed after {max_retries} attempts: {e}")
                return False

    return False

def capture_image():
    """
    Capture still image from CSI camera RTSP stream without stopping MediaMTX.

    Extracts a single frame from the live RTSP stream using ffmpeg.
    This avoids disrupting the live stream and eliminates the need to stop/restart MediaMTX.
    The captured frame is 1920x1080 (stream resolution) instead of 2592x1944,
    but this is sufficient for feed level detection and much faster.

    Returns:
        numpy.ndarray: Captured image as OpenCV BGR array, or None on failure
    """
    try:
        # Capture single frame from RTSP stream using ffmpeg
        cmd = [
            'ffmpeg',
            '-rtsp_transport', 'tcp',
            '-i', 'rtsp://localhost:8554/csi_camera',
            '-frames:v', '1',
            '-q:v', '2',
            '-y',
            IMAGE_PATH
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"✗ RTSP frame capture failed: {result.stderr[-200:]}")  # Last 200 chars
            return None

        # Load image with OpenCV
        if not os.path.exists(IMAGE_PATH):
            print(f"✗ Image file not created: {IMAGE_PATH}")
            return None

        image = cv2.imread(IMAGE_PATH)
        if image is None:
            print(f"✗ Could not load image: {IMAGE_PATH}")
            return None

        print(f"✓ RTSP frame captured: {image.shape[1]}x{image.shape[0]}")
        return image

    except subprocess.TimeoutExpired:
        print(f"✗ RTSP capture timed out")
        return None
    except Exception as e:
        print(f"✗ Image capture failed: {e}")
        return None

def validate_image_quality(image):
    """
    Validate image quality using blur detection and brightness analysis.

    Args:
        image: OpenCV BGR image array

    Returns:
        tuple: (is_valid, quality_score, blur_score, brightness)
    """
    try:
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Blur detection using Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_score = round(laplacian_var, 2)

        # Brightness analysis
        brightness = round(np.mean(gray), 2)

        # Quality validation
        is_blurry = blur_score < BLUR_THRESHOLD
        is_too_dark = brightness < BRIGHTNESS_MIN
        is_too_bright = brightness > BRIGHTNESS_MAX

        is_valid = not (is_blurry or is_too_dark or is_too_bright)

        # Calculate overall quality score (0-100)
        blur_quality = min(100, (blur_score / BLUR_THRESHOLD) * 100) if BLUR_THRESHOLD > 0 else 100
        brightness_quality = 100
        if is_too_dark:
            brightness_quality = (brightness / BRIGHTNESS_MIN) * 100
        elif is_too_bright:
            brightness_quality = (1 - ((brightness - BRIGHTNESS_MAX) / (255 - BRIGHTNESS_MAX))) * 100

        quality_score = round((blur_quality + brightness_quality) / 2, 1)

        return is_valid, quality_score, blur_score, brightness

    except Exception as e:
        print(f"✗ Image quality validation failed: {e}")
        return False, 0, 0, 0

def detect_jar(image):
    """
    Detect glass jar feeder in image using contour analysis.

    Since the ROI is already tightly focused on the jar, we assume the jar
    fills most of the ROI and use simple validation.

    Args:
        image: OpenCV BGR image array

    Returns:
        tuple: (jar_detected, jar_contour, jar_roi)
               jar_roi is (x, y, w, h) of bounding rectangle
    """
    try:
        # Extract ROI from full image
        x, y, w, h = ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT
        roi = image[y:y+h, x:x+w]

        # Since ROI is already focused on jar, use the full ROI as jar area
        # This is more reliable than edge detection which can fail with glass reflections
        jar_roi = (0, 0, w, h)  # Full ROI in ROI coordinates

        # Simple validation: check if image has reasonable content
        # (not all black/white, which would indicate camera failure)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)

        # If brightness is reasonable, assume jar is present
        if 20 < mean_brightness < 240:
            return True, None, jar_roi
        else:
            return False, None, None

    except Exception as e:
        print(f"✗ Jar detection failed: {e}")
        return False, None, None

def validate_roi_alignment(image):
    """
    Validate that ROI contains reasonable image content to detect misalignment.

    This performs sanity checks on the ROI to catch catastrophic misalignment
    (jar moved, camera shifted, etc.) before attempting feed measurement.

    Checks performed:
    1. Brightness range (20-240) - not all black or all white
    2. Texture variance (>10) - has some detail, not uniform
    3. Edge density (0.01-0.5) - reasonable amount of edges

    Args:
        image: Full OpenCV BGR image

    Returns:
        tuple: (is_valid: bool, message: str)
    """
    try:
        # Extract ROI
        x, y, w, h = ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT
        roi = image[y:y+h, x:x+w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # Check 1: Brightness should be reasonable
        mean_brightness = np.mean(gray)
        if mean_brightness < 20:
            return False, f'ROI too dark ({mean_brightness:.1f}) - possible misalignment'
        if mean_brightness > 240:
            return False, f'ROI too bright ({mean_brightness:.1f}) - possible glare/misalignment'

        # Check 2: Should have texture (not uniform)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if laplacian_var < 10:
            return False, f'No texture detected (var={laplacian_var:.1f}) - ROI may be off-target'

        # Check 3: Edge density should be reasonable
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / (w * h)
        if edge_density < 0.01:
            return False, f'Very low edge density ({edge_density:.1%}) - possible misalignment'
        if edge_density > 0.5:
            return False, f'Very high edge density ({edge_density:.1%}) - possible obstruction'

        return True, f'ROI validated (brightness={mean_brightness:.1f}, texture={laplacian_var:.1f}, edges={edge_density:.1%})'

    except Exception as e:
        return False, f'Validation error: {e}'

def measure_feed_level(image):
    """
    Measure feed level in jar using top-down row scanning.

    This method scans from top to bottom looking for the first "dense" row
    of feed-colored pixels, which represents the feed surface level.
    This is more robust than pixel counting because it's not affected by:
    - Feed distribution (clumpy vs. evenly spread)
    - Glass reflections below the feed surface
    - Lighting variations

    Args:
        image: OpenCV BGR image array

    Returns:
        dict: Feed level data including percentage, classification, and raw measurements
    """
    try:
        # Extract ROI from full image
        x, y, w, h = ROI_X, ROI_Y, ROI_WIDTH, ROI_HEIGHT
        roi = image[y:y+h, x:x+w]

        # Detect jar
        jar_detected, jar_contour, jar_roi = detect_jar(image)

        if not jar_detected:
            return {
                'jar_detected': False,
                'level_percentage': 0,
                'level_classification': 'UNKNOWN',
                'confidence': 0,
                'raw_feed_pixels': 0,
                'raw_total_pixels': 0,
                'feed_surface_y': -1
            }

        # Convert ROI to HSV for color-based segmentation
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Create mask for feed color (configurable HSV range)
        lower_bound = np.array(FEED_COLOR_HSV_MIN)
        upper_bound = np.array(FEED_COLOR_HSV_MAX)
        feed_mask = cv2.inRange(hsv, lower_bound, upper_bound)

        # TOP-DOWN SCANNING: Multi-method detection for accuracy
        # Uses brightness gradient + HSV color + edge detection with cross-validation
        feed_surface_y = -1  # -1 means not detected
        roi_height, roi_width = feed_mask.shape

        # ========== METHOD 1: HSV Color-based Gradient (original) ==========
        densities = []
        # FIXED: Scan from FULL_Y (top) to EMPTY_Y (bottom) - correct direction!
        scan_start = max(FEED_LEVEL_FULL_Y + 5, 0)  # Skip marker line area
        scan_end = min(FEED_LEVEL_EMPTY_Y - 5, roi_height)  # Skip marker line area

        for row_y in range(scan_start, scan_end):
            row_pixels = np.sum(feed_mask[row_y, :] > 0)
            row_density = row_pixels / roi_width
            densities.append((row_y, row_density))

        max_gradient_hsv = 0
        max_gradient_y_hsv = -1
        window_size = GRADIENT_WINDOW_SIZE

        if len(densities) > window_size:
            for i in range(len(densities) - window_size):
                y_start, density_start = densities[i]
                y_end, density_end = densities[i + window_size]
                gradient = (density_end - density_start) / window_size

                if gradient > max_gradient_hsv:
                    max_gradient_hsv = gradient
                    max_gradient_y_hsv = y_end

        # ========== METHOD 2: Brightness Gradient (Value channel) ==========
        value_channel = hsv[:, :, 2]
        brightness_rows = []

        for row_y in range(scan_start, scan_end):
            # Sample center 80% of row to avoid jar edges
            mid_start = int(roi_width * 0.1)
            mid_end = int(roi_width * 0.9)
            row_brightness = np.mean(value_channel[row_y, mid_start:mid_end])
            brightness_rows.append((row_y, row_brightness))

        max_gradient_brightness = 0
        max_gradient_y_brightness = -1

        if len(brightness_rows) > window_size:
            for i in range(len(brightness_rows) - window_size):
                y_start, brightness_start = brightness_rows[i]
                y_end, brightness_end = brightness_rows[i + window_size]
                # Look for brightness DROP (feed is darker than empty space)
                gradient = abs(brightness_start - brightness_end) / window_size

                if gradient > max_gradient_brightness and gradient > 5.0:  # Minimum threshold
                    max_gradient_brightness = gradient
                    max_gradient_y_brightness = y_end

        # ========== METHOD 3: Edge Detection ==========
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 30, 100)

        edge_counts = []
        for row_y in range(scan_start, scan_end):
            edge_count = np.sum(edges[row_y, :] > 0)
            edge_counts.append((row_y, edge_count))

        # Find row with most edges (likely the feed surface)
        max_edges = 0
        max_edges_y = -1
        for y, count in edge_counts:
            if count > max_edges and count > 5:  # Minimum edge threshold
                max_edges = count
                max_edges_y = y

        # ========== CROSS-VALIDATION: Combine methods ==========
        candidates = []
        if max_gradient_y_hsv > 0:
            surface_density = next((d for y, d in densities if y == max_gradient_y_hsv), 0)
            if surface_density >= DENSITY_THRESHOLD:
                candidates.append(('HSV', max_gradient_y_hsv, max_gradient_hsv))

        if max_gradient_y_brightness > 0:
            candidates.append(('Brightness', max_gradient_y_brightness, max_gradient_brightness))

        if max_edges_y > 0:
            candidates.append(('Edges', max_edges_y, max_edges / roi_width))

        if len(candidates) >= 2:
            # If multiple methods agree (within 15 pixels), use average
            y_values = [y for _, y, _ in candidates]
            if max(y_values) - min(y_values) <= 15:
                feed_surface_y = int(np.mean(y_values))
                methods = ', '.join([m for m, _, _ in candidates])
                print(f"  DEBUG: Feed surface at Y={feed_surface_y} (methods: {methods} - CONSENSUS)")
            else:
                # Use brightness method as tiebreaker (most reliable under pink lights)
                if max_gradient_y_brightness > 0:
                    feed_surface_y = max_gradient_y_brightness
                    print(f"  DEBUG: Feed surface at Y={feed_surface_y} (brightness gradient, no consensus)")
                elif max_gradient_y_hsv > 0:
                    feed_surface_y = max_gradient_y_hsv
                    print(f"  DEBUG: Feed surface at Y={feed_surface_y} (HSV gradient, no consensus)")
        elif len(candidates) == 1:
            method, y, strength = candidates[0]
            feed_surface_y = y
            print(f"  DEBUG: Feed surface at Y={feed_surface_y} (single method: {method})")
        else:
            print(f"  DEBUG: No significant feed surface detected by any method")

        # Calculate feed level percentage based on Y position
        if feed_surface_y >= 0:
            # Calculate percentage: 100% at FULL_Y=50 (top), 0% at EMPTY_Y=174 (bottom)
            # Y-axis increases downward, so smaller Y = more full
            y_range = FEED_LEVEL_EMPTY_Y - FEED_LEVEL_FULL_Y  # 174 - 50 = 124 pixels
            y_offset = feed_surface_y - FEED_LEVEL_FULL_Y      # Distance from FULL line
            level_percentage = max(0, min(100, 100 - (y_offset / y_range * 100)))
        else:
            # No feed detected - jar is empty
            level_percentage = 0
            feed_surface_y = FEED_LEVEL_EMPTY_Y  # Report empty position

        # Classify feed level
        if level_percentage >= LEVEL_THRESHOLD_FULL:
            level_classification = 'FULL'
        elif level_percentage >= LEVEL_THRESHOLD_MEDIUM:
            level_classification = 'MEDIUM'
        elif level_percentage >= LEVEL_THRESHOLD_LOW:
            level_classification = 'LOW'
        else:
            level_classification = 'EMPTY'

        # Calculate confidence based on how well-defined the feed surface is
        # Check density of rows around detected surface
        confidence = 0
        if feed_surface_y >= 0 and feed_surface_y < roi_height:
            window_start = max(0, feed_surface_y - 2)
            window_end = min(roi_height, feed_surface_y + 3)
            window_pixels = np.sum(feed_mask[window_start:window_end, :] > 0)
            window_area = (window_end - window_start) * roi_width
            if window_area > 0:
                confidence = min(100, (window_pixels / window_area) * 200)  # Scale to 0-100
        confidence = round(confidence, 1)

        # Count total feed pixels for debugging
        feed_pixels = np.sum(feed_mask > 0)
        jar_x, jar_y, jar_w, jar_h = jar_roi
        jar_pixels = jar_w * jar_h

        return {
            'jar_detected': True,
            'level_percentage': round(level_percentage, 1),
            'level_classification': level_classification,
            'confidence': confidence,
            'raw_feed_pixels': int(feed_pixels),
            'raw_total_pixels': int(jar_pixels),
            'feed_surface_y': int(feed_surface_y)  # Y-position within ROI
        }

    except Exception as e:
        print(f"✗ Feed level measurement failed: {e}")
        return {
            'jar_detected': False,
            'level_percentage': 0,
            'level_classification': 'ERROR',
            'confidence': 0,
            'raw_feed_pixels': 0,
            'raw_total_pixels': 0,
            'feed_surface_y': -1
        }

def publish_last_known_value():
    """
    Republish the last valid feed reading during lights-out hours.

    This prevents false EMPTY readings when the camera cannot see properly in the dark.
    The published data includes a 'state' field indicating it's a retained value.
    """
    global last_valid_reading

    if last_valid_reading is None:
        print("⚠️  No last known value to publish (lights are OFF)")
        return

    # Update timestamp but keep all other data from last valid reading
    republished_data = last_valid_reading.copy()
    republished_data['timestamp'] = int(time.time())
    republished_data['state'] = 'lights_off_retained'  # Indicate this is a retained value

    mqtt_client.publish('beeper/feed/level/current', json.dumps(republished_data))
    print(f"📤 Republished last known value: {republished_data['level']} ({republished_data['percentage']:.1f}%) [LIGHTS OFF]")

def publish_feed_data(feed_data, image_quality):
    """
    Publish feed level data to MQTT topics.

    Args:
        feed_data: Dict containing feed level measurements
        image_quality: Tuple of (is_valid, quality_score, blur_score, brightness)
    """
    global feed_history, last_valid_reading
    timestamp = int(time.time())

    is_valid, quality_score, blur_score, brightness = image_quality

    # Update feed history
    feed_history.append(feed_data['level_percentage'])
    if len(feed_history) > FEED_HISTORY_SIZE:
        feed_history.pop(0)

    # Calculate trend (increasing, decreasing, stable)
    trend = 'stable'
    if len(feed_history) >= 2:
        recent_avg = np.mean(feed_history[-2:])
        older_avg = np.mean(feed_history[:-2]) if len(feed_history) > 2 else feed_history[0]
        diff = recent_avg - older_avg
        if abs(diff) > 5:  # More than 5% change
            trend = 'decreasing' if diff < 0 else 'increasing'

    # Publish current feed level
    current_data = {
        'level': feed_data['level_classification'],
        'percentage': feed_data['level_percentage'],
        'jar_detected': feed_data['jar_detected'],
        'confidence': feed_data['confidence'],
        'method': feed_data.get('method', 'unknown'),  # ML method identifier
        'image_quality': quality_score,
        'blur_score': blur_score,
        'brightness': brightness,
        'trend': trend,
        'state': 'lights_on_fresh',  # Fresh reading taken during lights-on hours
        'timestamp': timestamp,
        'sensor_type': 'camera',
        'location': 'raspberry_pi'
    }
    mqtt_client.publish('beeper/feed/level/current', json.dumps(current_data))

    # Store this as the last valid reading (for use during lights-out)
    last_valid_reading = current_data.copy()

    # Publish raw measurements
    raw_data = {
        'feed_pixels': feed_data['raw_feed_pixels'],
        'total_pixels': feed_data['raw_total_pixels'],
        'feed_surface_y': feed_data.get('feed_surface_y', -1),  # Y-position within ROI
        'roi_x': ROI_X,
        'roi_y': ROI_Y,
        'roi_width': ROI_WIDTH,
        'roi_height': ROI_HEIGHT,
        'timestamp': timestamp,
        'sensor_type': 'camera',
        'location': 'raspberry_pi'
    }
    mqtt_client.publish('beeper/feed/level/raw', json.dumps(raw_data))

    # Publish alerts if needed
    alert_type = None
    severity = None
    message = None

    if not feed_data['jar_detected']:
        alert_type = 'jar_missing'
        severity = 'critical'
        message = 'Feed jar not detected in camera view'
    elif not is_valid:
        alert_type = 'image_quality'
        severity = 'warning'
        message = f'Poor image quality: blur={blur_score:.1f}, brightness={brightness:.1f}'
    elif feed_data['level_percentage'] < LEVEL_THRESHOLD_LOW:
        alert_type = 'feed_empty'
        severity = 'warning'
        message = f'Feed level critically low: {feed_data["level_percentage"]:.1f}%'
    elif feed_data['level_percentage'] < LEVEL_THRESHOLD_MEDIUM:
        alert_type = 'feed_low'
        severity = 'info'
        message = f'Feed level low: {feed_data["level_percentage"]:.1f}%'

    if alert_type:
        alert_data = {
            'alert_type': alert_type,
            'severity': severity,
            'message': message,
            'level_percentage': feed_data['level_percentage'],
            'timestamp': timestamp,
            'sensor_type': 'camera',
            'location': 'raspberry_pi'
        }
        mqtt_client.publish('beeper/feed/alerts/status', json.dumps(alert_data))

    # Log to console
    print(f"📤 Feed: {feed_data['level_classification']} ({feed_data['level_percentage']:.1f}%) | "
          f"Quality: {quality_score:.0f} | Trend: {trend}")
    if alert_type:
        print(f"⚠️  Alert: {message}")

def monitor_feed():
    """Main monitoring cycle - capture, analyze, and publish feed data."""
    try:
        print(f"\n{'='*60}")
        print(f"Feed Monitor Cycle - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        # Check if lights are currently ON
        lights_on, current_time_et = get_current_lights_state()
        print(f"🕒 Current time: {current_time_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"💡 Lights state: {'ON' if lights_on else 'OFF'}")

        # If lights are OFF, republish last known value and return
        if not lights_on:
            print("🌙 Lights are OFF - republishing last known feed level")
            publish_last_known_value()
            return

        # Lights are ON - take fresh reading
        print("☀️  Lights are ON - taking fresh feed reading")

        # Capture image
        image = capture_image()
        if image is None:
            print(f"✗ Failed to capture image, skipping cycle")
            return

        # Validate image quality
        is_valid, quality_score, blur_score, brightness = validate_image_quality(image)
        print(f"✓ Image quality: {quality_score:.0f} (blur={blur_score:.1f}, brightness={brightness:.1f})")

        if not is_valid:
            print(f"⚠️  Image quality below threshold, results may be inaccurate")

        # Validate ROI alignment
        alignment_ok, alignment_msg = validate_roi_alignment(image)
        print(f"✓ ROI alignment: {alignment_msg}")

        if not alignment_ok:
            print(f"⚠️  ROI alignment check FAILED - skipping measurement")
            # Publish alert
            alert_data = {
                'alert_type': 'roi_alignment_failed',
                'severity': 'warning',
                'message': alignment_msg,
                'timestamp': int(time.time()),
                'sensor_type': 'camera',
                'location': 'raspberry_pi'
            }
            mqtt_client.publish('beeper/feed/alerts/status', json.dumps(alert_data))
            return  # Skip this cycle

        # Predict feed level using ML model
        ml_result = predict_feed_level_ml(image)

        if ml_result['success']:
            # Convert ML prediction to feed_data format for compatibility
            level_percentage = ml_result['percentage']

            # Classify feed level based on thresholds
            if level_percentage >= LEVEL_THRESHOLD_FULL:
                level_classification = 'FULL'
            elif level_percentage >= LEVEL_THRESHOLD_MEDIUM:
                level_classification = 'MEDIUM'
            elif level_percentage >= LEVEL_THRESHOLD_LOW:
                level_classification = 'LOW'
            else:
                level_classification = 'EMPTY'

            feed_data = {
                'jar_detected': True,
                'level_percentage': level_percentage,
                'level_classification': level_classification,
                'confidence': ml_result['confidence'],
                'raw_feed_pixels': 0,  # Not applicable for ML
                'raw_total_pixels': 0,
                'feed_surface_y': -1,  # Not applicable for ML
                'method': ml_result['method']
            }

            print(f"✓ ML Prediction: {level_classification} ({level_percentage:.1f}%) "
                  f"[confidence: {ml_result['confidence']:.0f}%]")
        else:
            # ML prediction failed
            print(f"✗ ML prediction failed: {ml_result['error']}")
            feed_data = {
                'jar_detected': False,
                'level_percentage': 0,
                'level_classification': 'ERROR',
                'confidence': 0,
                'raw_feed_pixels': 0,
                'raw_total_pixels': 0,
                'feed_surface_y': -1,
                'method': 'ml_tflite_error'
            }

        # Publish to MQTT (and store as last valid reading)
        publish_feed_data(feed_data, (is_valid, quality_score, blur_score, brightness))

    except Exception as e:
        print(f"✗ Monitor cycle failed: {e}")

def main():
    """Main loop for feed monitor."""
    print("🐔 BEEPER KEEPER - Feed Monitor (ML-Powered)")
    print("=" * 60)
    print(f"Camera: CSI Camera (RTSP stream capture)")
    print(f"Resolution: {IMAGE_WIDTH}x{IMAGE_HEIGHT}")
    print(f"ROI: ({ROI_X}, {ROI_Y}, {ROI_WIDTH}, {ROI_HEIGHT})")
    print(f"ML Model: MobileNetV2 (4.80% MAE)")
    print(f"ML Input Size: {ML_INPUT_SIZE}")
    print(f"Interval: {CAPTURE_INTERVAL_SECONDS} seconds ({CAPTURE_INTERVAL_SECONDS//60} minutes)")
    print("=" * 60)

    # Initialize TFLite model
    print("\nInitializing ML model...")
    if not init_tflite_model():
        print("✗ Failed to initialize TFLite model. Exiting.")
        return

    # Initialize MQTT
    print("\nInitializing MQTT connection...")
    if not init_mqtt():
        print("✗ Failed to initialize MQTT. Exiting.")
        return

    # Wait for MQTT connection
    time.sleep(2)

    print(f"\n📡 Monitoring feed every {CAPTURE_INTERVAL_SECONDS//60} minutes")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            monitor_feed()
            print(f"\n💤 Sleeping for {CAPTURE_INTERVAL_SECONDS} seconds...\n")
            time.sleep(CAPTURE_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down feed monitor...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("✓ Disconnected from MQTT broker")

if __name__ == "__main__":
    main()
