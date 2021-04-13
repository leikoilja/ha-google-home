"""Constants for Google Home."""
from typing import Final, List

from homeassistant.util.dt import DATE_STR_FORMAT

# Base component constants
NAME: Final[str] = "Google Home community driven integration"
DOMAIN: Final[str] = "google_home"
DOMAIN_DATA: Final[str] = f"{DOMAIN}_data"
MANUFACTURER: Final[str] = "google_home"

ATTRIBUTION: Final[str] = "json"
ISSUE_URL: Final[str] = "https://github.com/leikoilja/ha-google-home/issues"
CONF_DATA_COLLECTION: Final[str] = "data_collection"

DATA_CLIENT: Final[str] = "client"
DATA_COORDINATOR: Final[str] = "coordinator"

ALARM_AND_TIMER_ID_LENGTH: Final[int] = 42

# Icons
ICON_TOKEN: Final[str] = "mdi:form-textbox-password"
ICON_ALARMS: Final[str] = "mdi:alarm-multiple"
ICON_TIMERS: Final[str] = "mdi:timer-sand"
ICON_DO_NOT_DISTURB: Final[str] = "mdi:minus-circle"

# Device classes
BINARY_SENSOR_DEVICE_CLASS: Final[str] = "connectivity"

# Platforms
SENSOR: Final[str] = "sensor"
SWITCH: Final[str] = "switch"
PLATFORMS: Final[List[str]] = [SENSOR, SWITCH]

# Services
SERVICE_REBOOT: Final[str] = "reboot_device"
SERVICE_DELETE_ALARM: Final[str] = "delete_alarm"
SERVICE_DELETE_TIMER: Final[str] = "delete_timer"
SERVICE_ATTR_ALARM_ID: Final[str] = "alarm_id"
SERVICE_ATTR_TIMER_ID: Final[str] = "timer_id"

# Configuration and options
CONF_ANDROID_ID: Final[str] = "android_id"
CONF_USERNAME: Final[str] = "username"
CONF_PASSWORD: Final[str] = "password"
CONF_MASTER_TOKEN: Final[str] = "master_token"

# Defaults
DEFAULT_NAME: Final[str] = "Google Home"

LABEL_ALARMS: Final[str] = "alarms"
LABEL_AVAILABLE: Final[str] = "available"
LABEL_TIMERS: Final[str] = "timers"
LABEL_DEVICE: Final[str] = "device"
LABEL_DO_NOT_DISTURB: Final[str] = "Do Not Disturb"

# DEVICE PORT
PORT: Final[int] = 8443

# API
API_ENDPOINT_ALARMS: Final[str] = "setup/assistant/alarms"
API_ENDPOINT_DELETE: Final[str] = "setup/assistant/alarms/delete"
API_ENDPOINT_REBOOT: Final[str] = "setup/reboot"
API_ENDPOINT_DO_NOT_DISTURB: Final[str] = "setup/assistant/notifications"

# HEADERS
HEADER_CAST_LOCAL_AUTH: Final[str] = "cast-local-authorization-token"
HEADER_CONTENT_TYPE: Final[str] = "content-type"

TIMEOUT: Final[int] = 2  # Request Timeout in seconds

# TIMESTRINGS
TIME_STR_FORMAT: Final[str] = "%H:%M:%S"
DATETIME_STR_FORMAT: Final[str] = f"{DATE_STR_FORMAT} {TIME_STR_FORMAT}"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
UPDATE_INTERVAL: Final[int] = 10  # sec

# JSON parameter values when retrieving information from devices
JSON_ALARM: Final[str] = "alarm"
JSON_TIMER: Final[str] = "timer"
JSON_NOTIFICATIONS_ENABLED: Final[str] = "notifications_enabled"

STARTUP_MESSAGE: Final[
    str
] = f"""
-------------------------------------------------------------------
{NAME}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
