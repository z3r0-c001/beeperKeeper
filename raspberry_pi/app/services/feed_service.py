"""
Feed Service

ML feed level detection, ROI management, and calibration.
"""
import os
import json
import time
import threading
import subprocess
import re
import cv2
import numpy as np
from datetime import datetime
from io import BytesIO
from PIL import Image


class FeedService:
    """Feed monitoring and ML inference"""

    def __init__(self, config):
        # config is Flask's config dict, access via .get() or []
        self.calibration_dir = config.get('CALIBRATION_DATA_DIR', '/opt/beeperKeeper/calibration_data')
        self.training_dir = config.get('TRAINING_DATA_DIR', '/opt/beeperKeeper/feed_training_data')
        self.training_images_dir = os.path.join(self.training_dir, 'images')
        self.training_labels_dir = os.path.join(self.training_dir, 'labels')
        self.cache_duration = config.get('ROI_CACHE_DURATION', 30)

        # ROI image cache
        self._cache = {
            'image_data': None,
            'timestamp': 0
        }
        self._cache_lock = threading.Lock()

        # Ensure directories exist
        os.makedirs(self.calibration_dir, exist_ok=True)
        os.makedirs(self.training_images_dir, exist_ok=True)
        os.makedirs(self.training_labels_dir, exist_ok=True)

    def get_feed_config(self):
        """Read current feed configuration from feed_config.py"""
        config_path = '/opt/beeperKeeper/feed_config.py'
        try:
            with open(config_path, 'r') as f:
                content = f.read()

            # Parse values using regex
            def get_value(pattern, content, default=0):
                match = re.search(pattern, content)
                return int(match.group(1)) if match else default

            return {
                'roi_x': get_value(r'ROI_X\s*=\s*(\d+)', content),
                'roi_y': get_value(r'ROI_Y\s*=\s*(\d+)', content),
                'roi_width': get_value(r'ROI_WIDTH\s*=\s*(\d+)', content),
                'roi_height': get_value(r'ROI_HEIGHT\s*=\s*(\d+)', content),
                'full_y': get_value(r'FEED_LEVEL_FULL_Y\s*=\s*(\d+)', content),
                'empty_y': get_value(r'FEED_LEVEL_EMPTY_Y\s*=\s*(\d+)', content)
            }
        except Exception as e:
            print(f"Error reading feed config: {e}")
            return None

    def save_feed_config(self, roi_x=None, roi_y=None, roi_width=None, roi_height=None,
                         full_y=None, empty_y=None):
        """Update feed_config.py with new values"""
        config_path = '/opt/beeperKeeper/feed_config.py'
        try:
            with open(config_path, 'r') as f:
                content = f.read()

            # Update values if provided
            if roi_x is not None:
                content = re.sub(r'ROI_X\s*=\s*\d+', f'ROI_X = {roi_x}', content)
            if roi_y is not None:
                content = re.sub(r'ROI_Y\s*=\s*\d+', f'ROI_Y = {roi_y}', content)
            if roi_width is not None:
                content = re.sub(r'ROI_WIDTH\s*=\s*\d+', f'ROI_WIDTH = {roi_width}', content)
            if roi_height is not None:
                content = re.sub(r'ROI_HEIGHT\s*=\s*\d+', f'ROI_HEIGHT = {roi_height}', content)
            if full_y is not None:
                content = re.sub(r'FEED_LEVEL_FULL_Y\s*=\s*\d+', f'FEED_LEVEL_FULL_Y = {full_y}', content)
            if empty_y is not None:
                content = re.sub(r'FEED_LEVEL_EMPTY_Y\s*=\s*\d+', f'FEED_LEVEL_EMPTY_Y = {empty_y}', content)

            # Update calibration date
            today = datetime.now().strftime('%Y-%m-%d')
            content = re.sub(
                r"CALIBRATION_DATE\s*=\s*['\"].*?['\"]",
                f"CALIBRATION_DATE = '{today}'",
                content
            )

            with open(config_path, 'w') as f:
                f.write(content)

            return True
        except Exception as e:
            print(f"Error saving feed config: {e}")
            return False

    def capture_image(self, timeout=20):
        """Capture a still image from the camera"""
        capture_script = '/opt/beeperKeeper/capture_feed_still.sh'
        try:
            result = subprocess.run(
                [capture_script],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            print("Image capture timeout")
            return False
        except Exception as e:
            print(f"Capture error: {e}")
            return False

    def get_roi_image(self, force_fresh=False):
        """Get ROI image, using cache if available"""
        with self._cache_lock:
            current_time = time.time()
            cache_age = current_time - self._cache['timestamp']

            # Return cached if valid
            if (self._cache['image_data'] is not None and
                    cache_age < self.cache_duration and
                    not force_fresh):
                return self._cache['image_data']

            # Capture fresh image
            if not self.capture_image():
                return None

            # Load and extract ROI
            config = self.get_feed_config()
            if not config:
                return None

            image_path = '/tmp/feed_monitor_current.jpg'
            if not os.path.exists(image_path):
                return None

            image = cv2.imread(image_path)
            if image is None:
                return None

            # Extract ROI
            roi = image[
                config['roi_y']:config['roi_y'] + config['roi_height'],
                config['roi_x']:config['roi_x'] + config['roi_width']
            ]

            # Convert to JPEG
            roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(roi_rgb)
            buffer = BytesIO()
            pil_image.save(buffer, format='JPEG', quality=95)
            roi_jpeg = buffer.getvalue()

            # Update cache
            self._cache['image_data'] = roi_jpeg
            self._cache['timestamp'] = current_time

            return roi_jpeg

    def get_full_frame(self):
        """Get full camera frame"""
        if not self.capture_image():
            return None

        image_path = '/tmp/feed_monitor_current.jpg'
        if not os.path.exists(image_path):
            return None

        image = cv2.imread(image_path)
        if image is None:
            return None

        # Convert to JPEG
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(image_rgb)
        buffer = BytesIO()
        pil_image.save(buffer, format='JPEG', quality=95)
        return buffer.getvalue()

    def save_training_sample(self, y_position, percent_full):
        """Save a training sample for ML model"""
        config = self.get_feed_config()
        if not config:
            return None, "Could not read feed config"

        image_path = '/tmp/feed_monitor_current.jpg'
        if not os.path.exists(image_path):
            return None, "No image available"

        image = cv2.imread(image_path)
        if image is None:
            return None, "Could not load image"

        # Extract ROI
        roi = image[
            config['roi_y']:config['roi_y'] + config['roi_height'],
            config['roi_x']:config['roi_x'] + config['roi_width']
        ]

        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        image_filename = f'feed_{timestamp}.jpg'
        label_filename = f'feed_{timestamp}.json'

        # Save ROI image
        image_path = os.path.join(self.training_images_dir, image_filename)
        cv2.imwrite(image_path, roi, [cv2.IMWRITE_JPEG_QUALITY, 95])

        # Save label
        label_data = {
            'image_filename': image_filename,
            'y_position': y_position,
            'percent_full': round(percent_full, 1),
            'timestamp': datetime.now().isoformat(),
            'roi_coords': {
                'x': config['roi_x'],
                'y': config['roi_y'],
                'width': config['roi_width'],
                'height': config['roi_height']
            }
        }

        label_path = os.path.join(self.training_labels_dir, label_filename)
        with open(label_path, 'w') as f:
            json.dump(label_data, f, indent=2)

        # Count samples
        samples = len([f for f in os.listdir(self.training_labels_dir) if f.endswith('.json')])

        return samples, None

    def get_training_progress(self):
        """Get training data collection progress"""
        try:
            label_files = [f for f in os.listdir(self.training_labels_dir) if f.endswith('.json')]
            samples_collected = len(label_files)

            # Distribution by fill level
            distribution = {'0-25%': 0, '26-50%': 0, '51-75%': 0, '76-100%': 0}

            for label_file in label_files:
                label_path = os.path.join(self.training_labels_dir, label_file)
                with open(label_path, 'r') as f:
                    label_data = json.load(f)
                    percent = label_data.get('percent_full', 0)

                    if percent <= 25:
                        distribution['0-25%'] += 1
                    elif percent <= 50:
                        distribution['26-50%'] += 1
                    elif percent <= 75:
                        distribution['51-75%'] += 1
                    else:
                        distribution['76-100%'] += 1

            return {
                'samples_collected': samples_collected,
                'target': 150,
                'progress_percentage': round((samples_collected / 150) * 100, 1),
                'distribution': distribution
            }
        except Exception as e:
            print(f"Training progress error: {e}")
            return None

    def ml_predict(self):
        """Run ML inference on current ROI"""
        try:
            # Check model exists
            model_path = '/opt/beeperKeeper/models/feed_model.tflite'
            if not os.path.exists(model_path):
                return None, "Model not found"

            # Import TFLite
            try:
                import tflite_runtime.interpreter as tflite
            except ImportError:
                try:
                    import tensorflow.lite as tflite
                except ImportError:
                    return None, "TensorFlow Lite not installed"

            # Capture and load image
            if not self.capture_image():
                return None, "Image capture failed"

            config = self.get_feed_config()
            if not config:
                return None, "Could not read feed config"

            image_path = '/tmp/feed_monitor_current.jpg'
            image = cv2.imread(image_path)
            if image is None:
                return None, "Could not load image"

            # Extract ROI
            roi = image[
                config['roi_y']:config['roi_y'] + config['roi_height'],
                config['roi_x']:config['roi_x'] + config['roi_width']
            ]

            # Preprocess for MobileNetV2
            roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            roi_resized = cv2.resize(roi_rgb, (224, 224))
            roi_normalized = roi_resized.astype(np.float32) / 255.0
            input_data = np.expand_dims(roi_normalized, axis=0)

            # Run inference
            start_time = time.time()
            interpreter = tflite.Interpreter(model_path=model_path)
            interpreter.allocate_tensors()

            input_details = interpreter.get_input_details()
            output_details = interpreter.get_output_details()

            interpreter.set_tensor(input_details[0]['index'], input_data)
            interpreter.invoke()

            output = interpreter.get_tensor(output_details[0]['index'])
            prediction_percent = float(output[0][0])
            inference_time_ms = (time.time() - start_time) * 1000

            return {
                'prediction': round(prediction_percent, 1),
                'inference_time_ms': round(inference_time_ms, 1),
                'timestamp': datetime.now().isoformat()
            }, None

        except Exception as e:
            return None, str(e)

    def clear_cache(self):
        """Clear the ROI image cache"""
        with self._cache_lock:
            self._cache['image_data'] = None
            self._cache['timestamp'] = 0
