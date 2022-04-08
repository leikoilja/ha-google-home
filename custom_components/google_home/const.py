"""Constants for Google Home."""
from __future__ import annotations

from typing import Final

from homeassistant.util.dt import DATE_STR_FORMAT

# Base component constants
NAME: Final = "Google Home community driven integration"
DOMAIN: Final = "google_home"
DOMAIN_DATA: Final = f"{DOMAIN}_data"
MANUFACTURER: Final = "Google Home"

ATTRIBUTION: Final = "json"
ISSUE_URL: Final = "https://github.com/leikoilja/ha-google-home/issues"
CONF_UPDATE_INTERVAL: Final = "update_interval"

DATA_CLIENT: Final = "client"
DATA_COORDINATOR: Final = "coordinator"

ALARM_AND_TIMER_ID_LENGTH: Final = 42

MAX_PASSWORD_LENGTH: Final = 100

# Icons
ICON_TOKEN: Final = "mdi:form-textbox-password"
ICON_ALARMS: Final = "mdi:alarm-multiple"
ICON_TIMERS: Final = "mdi:timer-sand"
ICON_DO_NOT_DISTURB: Final = "mdi:minus-circle"
ICON_ALARM_VOLUME_LOW: Final = "mdi:volume-low"
ICON_ALARM_VOLUME_MID: Final = "mdi:volume-medium"
ICON_ALARM_VOLUME_HIGH: Final = "mdi:volume-high"
ICON_ALARM_VOLUME_OFF: Final = "mdi:volume-off"

# Device classes
BINARY_SENSOR_DEVICE_CLASS: Final = "connectivity"

# Platforms
SENSOR: Final = "sensor"
SWITCH: Final = "switch"
NUMBER: Final = "number"
PLATFORMS: Final = [SENSOR, SWITCH, NUMBER]

# Services
SERVICE_REBOOT: Final = "reboot_device"
SERVICE_DELETE_ALARM: Final = "delete_alarm"
SERVICE_DELETE_TIMER: Final = "delete_timer"
SERVICE_ATTR_ALARM_ID: Final = "alarm_id"
SERVICE_ATTR_TIMER_ID: Final = "timer_id"

# Configuration and options
CONF_ANDROID_ID: Final = "android_id"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_MASTER_TOKEN: Final = "master_token"

# Defaults
DEFAULT_NAME: Final = "Google Home"
GOOGLE_HOME_ALARM_DEFAULT_VALUE: Final = 0

LABEL_ALARMS: Final = "alarms"
LABEL_ALARM_VOLUME: Final = "alarm volume"
LABEL_AVAILABLE: Final = "available"
LABEL_TIMERS: Final = "timers"
LABEL_DEVICE: Final = "device"
LABEL_DO_NOT_DISTURB: Final = "Do Not Disturb"

# DEVICE PORT
PORT: Final = 8443

# API
API_ENDPOINT_ALARMS: Final = "setup/assistant/alarms"
API_ENDPOINT_ALARM_DELETE: Final = "setup/assistant/alarms/delete"
API_ENDPOINT_ALARM_VOLUME: Final = "setup/assistant/alarms/volume"
API_ENDPOINT_REBOOT: Final = "setup/reboot"
API_ENDPOINT_DO_NOT_DISTURB: Final = "setup/assistant/notifications"

# HEADERS
HEADER_CAST_LOCAL_AUTH: Final = "cast-local-authorization-token"
HEADER_CONTENT_TYPE: Final = "content-type"

TIMEOUT: Final = 2  # Request Timeout in seconds

# TIMESTRINGS
TIME_STR_FORMAT: Final = "%H:%M:%S"
DATETIME_STR_FORMAT: Final = f"{DATE_STR_FORMAT} {TIME_STR_FORMAT}"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
UPDATE_INTERVAL: Final = 180  # sec

# JSON parameter values when retrieving information from devices
JSON_ALARM: Final = "alarm"
JSON_TIMER: Final = "timer"
JSON_NOTIFICATIONS_ENABLED: Final = "notifications_enabled"
JSON_ALARM_VOLUME: Final = "volume"

STARTUP_MESSAGE: Final = f"""
-------------------------------------------------------------------
{NAME}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
