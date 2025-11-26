"""
BeeperKeeper Flask Configuration
"""
import os
from datetime import time as dtime


class Config:
    """Base configuration"""
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'beeper-keeper-secret-key-change-in-production')

    # MQTT
    MQTT_BROKER = os.getenv('MQTT_BROKER_HOST', '10.10.10.7')
    MQTT_PORT = int(os.getenv('MQTT_BROKER_PORT', 1883))

    # MediaMTX
    MEDIAMTX_HLS_PORT = 8888
    MEDIAMTX_WEBRTC_PORT = 8889

    # Email/SMTP
    SMTP_ENABLED = os.getenv('GF_SMTP_ENABLED', 'false').lower() == 'true'
    SMTP_HOST = os.getenv('GF_SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('GF_SMTP_PORT', '587'))
    SMTP_USER = os.getenv('GF_SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('GF_SMTP_PASSWORD', '')
    SMTP_FROM_ADDRESS = os.getenv('GF_SMTP_FROM_ADDRESS', 'beeper@YOUR_DOMAIN')
    SMTP_FROM_NAME = os.getenv('GF_SMTP_FROM_NAME', 'Beeper Keeper Alerts')

    # Light schedule
    LIGHTS_ON_TIME = dtime(6, 30)   # 6:30 AM
    LIGHTS_OFF_TIME = dtime(19, 0)  # 7:00 PM
    ALERT_MINUTES_BEFORE = 15

    # Rate limiting
    RATELIMIT_DEFAULT = "10000 per day, 3000 per hour"
    RATELIMIT_STORAGE_URI = "memory://"

    # Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, 'light_subscriptions.json')

    # Feed training
    CALIBRATION_DATA_DIR = '/opt/beeperKeeper/calibration_data'
    TRAINING_DATA_DIR = '/opt/beeperKeeper/feed_training_data'

    # Cache
    ROI_CACHE_DURATION = 30  # seconds

    # Chat
    MAX_CHAT_MESSAGES = 50


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False


# Config selector
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': ProductionConfig
}


def get_config():
    """Get configuration based on environment"""
    env = os.getenv('FLASK_ENV', 'production')
    return config.get(env, config['default'])
