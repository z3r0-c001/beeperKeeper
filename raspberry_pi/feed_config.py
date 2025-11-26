"""
Feed Monitor Configuration
===========================

Configuration file for BeeperKeeper feed monitoring system.
Optimized for Raspberry Pi 3B+ with OV5647 CSI camera (overhead view).

This file was recalibrated on 2025-11-23 to fix Y-coordinate mismatch.
ROI dimensions (140x237) are correct for current camera position.
Y-coordinates scaled from 292-sample training dataset (collected at 155x224).

FINAL CORRECTION APPLIED: 2025-11-23
- ROI dimensions set to 140x237 (correct jar framing for current camera)
- Y-coordinates SCALED from training data: 56→59 (FULL), 186→196 (EMPTY)
- Previous config had EMPTY_Y=272 which exceeded ROI_HEIGHT=237
"""

# MQTT Broker Configuration
MQTT_BROKER = '10.10.10.7'  # Docker host running Mosquitto
MQTT_PORT = 1883
MQTT_CLIENT_ID = 'beeper_feed_monitor'

# Camera Configuration
CAMERA_TYPE = 'csi'  # Changed from USB to CSI camera - 2025-11-18
CAMERA_DEVICE = '/dev/video0'  # CSI camera device (OV5647 - 5MP camera module)
IMAGE_WIDTH = 1920   # RTSP stream resolution
IMAGE_HEIGHT = 1080  # RTSP stream resolution
IMAGE_PATH = '/tmp/feed_monitor_current.jpg'  # Temporary storage (overwritten each cycle)

# Capture Timing
CAPTURE_INTERVAL_SECONDS = 60   # 1 minute (chickens eat quickly - need frequent monitoring)

# Region of Interest (ROI) - Overhead CSI camera view
# These coordinates define where in the image to look for the feed jar
# Updated 2025-11-23: Kept current deployed ROI (properly frames jar)
# ROI was manually adjusted for current camera mounting position
ROI_X = 957          # Jar center X-position (current camera setup)
ROI_Y = 663          # Jar top Y-position (current camera setup)
ROI_WIDTH = 140      # Jar width (current camera setup)
ROI_HEIGHT = 237     # Measurement height (current camera setup)

# Feed Level Y-Coordinates (within ROI coordinate system)
# Updated 2025-11-23: Scaled from 292-sample training dataset
# Training data (at 155x224 ROI): FULL_Y=56, EMPTY_Y=186
# Scaled to current ROI (140x237): multiply by 237/224 = 1.058
# FULL: 56 * 1.058 = 59
# EMPTY: 186 * 1.058 = 196
FEED_LEVEL_FULL_Y = 59       # Feed surface when jar is FULL (scaled from training)
FEED_LEVEL_EMPTY_Y = 196     # Feed surface when jar is EMPTY (scaled from training)
# Y-range: 137 pixels (adequate for gradient detection)

# Feed Color Detection (HSV color space)
# Calibrate these values based on your feed color
# Format: [Hue, Saturation, Value]
# Updated 2025-11-18: Recalibrated from actual feed at 50% level
# Analysis showed: Feed region has HIGHER saturation but LOWER brightness than empty space
#   Feed: H=132, S=167, V=186 (darker, more saturated)
#   Empty: H=122, S=154, V=205 (brighter, less saturated)
# Strategy: Target high saturation (>160) with medium-to-high brightness (100-200)
FEED_COLOR_HSV_MIN = [0, 160, 100]    # High saturation, allow darker values (feed is darker than empty space)
FEED_COLOR_HSV_MAX = [180, 255, 200]  # Cap brightness at 200 to exclude brighter empty regions

# Feed Level Detection Parameters
DENSITY_THRESHOLD = 0.15    # Minimum 15% of row must be feed-colored to count as "dense"
                            # Gradient detection finds transition point; threshold validates it's real feed
                            # May need adjustment for overhead view and higher resolution

GRADIENT_WINDOW_SIZE = 8    # Row window for gradient smoothing (increased from 5 for higher resolution)

# Feed Level Thresholds (percentage of jar filled)
LEVEL_THRESHOLD_FULL = 80    # Above this = FULL
LEVEL_THRESHOLD_MEDIUM = 40  # Above this = MEDIUM
LEVEL_THRESHOLD_LOW = 10     # Above this = LOW, below = EMPTY

# Image Quality Thresholds
BLUR_THRESHOLD = 70.0       # Minimum Laplacian variance (lowered for CSI stream - typical: 78-85)
BRIGHTNESS_MIN = 40         # Minimum average brightness (0-255)
BRIGHTNESS_MAX = 220        # Maximum average brightness (0-255)

# Calibration Metadata
CALIBRATION_DATE = '2025-11-23'  # Fixed Y-coordinates to match training dataset
CALIBRATION_VERSION = '2.6'      # Version 2.6 - Y-coords scaled from training, ROI dimensions preserved
