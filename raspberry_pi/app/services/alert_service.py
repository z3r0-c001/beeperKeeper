"""
Alert Service

Handles email alerts and light schedule notifications.
"""
import os
import json
import re
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, time as dtime
import pytz


class AlertService:
    """Email alert management"""

    def __init__(self, config):
        # config is Flask's config dict, access via .get() or []
        self.smtp_enabled = config.get('SMTP_ENABLED', False)
        self.smtp_host = config.get('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = config.get('SMTP_PORT', 587)
        self.smtp_user = config.get('SMTP_USER', '')
        self.smtp_password = config.get('SMTP_PASSWORD', '')
        self.from_address = config.get('SMTP_FROM_ADDRESS', 'beeper@YOUR_DOMAIN')
        self.from_name = config.get('SMTP_FROM_NAME', 'Beeper Keeper Alerts')
        self.subscriptions_file = config.get('SUBSCRIPTIONS_FILE', '/opt/beeperKeeper/light_subscriptions.json')
        self.lights_on_time = config.get('LIGHTS_ON_TIME', dtime(6, 30))
        self.lights_off_time = config.get('LIGHTS_OFF_TIME', dtime(19, 0))
        self.alert_minutes_before = config.get('ALERT_MINUTES_BEFORE', 15)
        self._lock = threading.Lock()

    def load_subscriptions(self):
        """Load email subscriptions from file"""
        try:
            if os.path.exists(self.subscriptions_file):
                with open(self.subscriptions_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading subscriptions: {e}")
            return {}

    def save_subscriptions(self, subs):
        """Save email subscriptions to file"""
        try:
            with self._lock:
                with open(self.subscriptions_file, 'w') as f:
                    json.dump(subs, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving subscriptions: {e}")
            return False

    @staticmethod
    def validate_email(email):
        """Validate email address format"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    def send_email(self, to_email, subject, html_content, text_content=None):
        """Send an email"""
        if not self.smtp_enabled:
            print(f"SMTP disabled, would send to {to_email}: {subject}")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_address}>"
            msg['To'] = to_email

            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            print(f"Email sent to {to_email}: {subject}")
            return True
        except Exception as e:
            print(f"Email send error: {e}")
            return False

    def send_light_alert(self, to_email, alert_type, alert_on=None, alert_off=None):
        """Send light schedule alert email"""
        est = pytz.timezone('America/New_York')
        now = datetime.now(est)

        if alert_type == 'lights_on':
            subject = "Beeper Keeper: Lights ON Soon"
            time_str = self.lights_on_time.strftime('%I:%M %p')
            html = f"""
            <h2>Lights turning ON soon</h2>
            <p>The coop lights will turn <strong>ON</strong> at {time_str} Eastern.</p>
            <p>Current time: {now.strftime('%I:%M %p %Z')}</p>
            """
        elif alert_type == 'lights_off':
            subject = "Beeper Keeper: Lights OFF Soon"
            time_str = self.lights_off_time.strftime('%I:%M %p')
            html = f"""
            <h2>Lights turning OFF soon</h2>
            <p>The coop lights will turn <strong>OFF</strong> at {time_str} Eastern.</p>
            <p>Current time: {now.strftime('%I:%M %p %Z')}</p>
            """
        elif alert_type == 'subscription':
            subject = "Beeper Keeper: Alert Subscription Confirmed"
            on_str = "Enabled" if alert_on else "Disabled"
            off_str = "Enabled" if alert_off else "Disabled"
            html = f"""
            <h2>Subscription Updated</h2>
            <p>Your alert preferences:</p>
            <ul>
                <li>Lights ON alerts: <strong>{on_str}</strong></li>
                <li>Lights OFF alerts: <strong>{off_str}</strong></li>
            </ul>
            """
        else:
            return False

        return self.send_email(to_email, subject, html)

    def send_scheduled_alerts(self, alert_type):
        """Send alerts to all subscribed users"""
        subs = self.load_subscriptions()
        alert_key = 'alert_on' if alert_type == 'lights_on' else 'alert_off'

        for email, prefs in subs.items():
            if prefs.get(alert_key, False):
                self.send_light_alert(email, alert_type)

    def get_lights_countdown(self):
        """Get countdown to next light change with progress info"""
        est = pytz.timezone('America/New_York')
        now = datetime.now(est)
        current_time = now.time()

        # Create datetime objects for today's schedule
        lights_on = now.replace(hour=self.lights_on_time.hour,
                                minute=self.lights_on_time.minute,
                                second=0, microsecond=0)
        lights_off = now.replace(hour=self.lights_off_time.hour,
                                 minute=self.lights_off_time.minute,
                                 second=0, microsecond=0)

        # Determine current phase and target
        if self.lights_on_time <= current_time < self.lights_off_time:
            # Daytime - countdown to lights off
            target = lights_off
            label = "COUNTDOWN TO LIGHTS OUT"
            phase = "day"
            emoji = "🌙"

            # Progress through the day
            day_duration = (lights_off - lights_on).total_seconds()
            elapsed = (now - lights_on).total_seconds()
            progress = (elapsed / day_duration) * 100 if day_duration > 0 else 0
        else:
            # Nighttime - countdown to lights on
            if current_time >= self.lights_off_time:
                # After lights off, next is tomorrow morning
                lights_on += timedelta(days=1)
            target = lights_on
            label = "COUNTDOWN TO LIGHTS ON"
            phase = "night"
            emoji = "☀️"

            # Progress through the night
            night_start = now.replace(hour=self.lights_off_time.hour,
                                      minute=self.lights_off_time.minute,
                                      second=0, microsecond=0)
            if current_time < self.lights_on_time:
                night_start -= timedelta(days=1)
            night_duration = (lights_on - night_start).total_seconds()
            elapsed = (now - night_start).total_seconds()
            progress = (elapsed / night_duration) * 100 if night_duration > 0 else 0

        progress = max(0, min(100, progress))

        # Calculate time remaining
        delta = target - now
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        return {
            'label': label,
            'emoji': emoji,
            'phase': phase,
            'hours': hours,
            'minutes': minutes,
            'seconds': seconds,
            'total_seconds': total_seconds,
            'progress': round(progress, 1),
            'target_time': target.strftime('%I:%M %p'),
            'current_time': now.strftime('%I:%M:%S %p'),
            'timestamp': now.isoformat()
        }


# Import timedelta for countdown calculation
from datetime import timedelta
