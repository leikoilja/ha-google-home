"""Constants for Google Home."""
from homeassistant.util.dt import DATE_STR_FORMAT

# Base component constants
NAME = "Google Home community driven integration"
DOMAIN = "google_home"
DOMAIN_DATA = f"{DOMAIN}_data"
MANUFACTURER = "google_home"

ATTRIBUTION = "json"
ISSUE_URL = "https://github.com/leikoilja/ha-google-home/issues"
CONF_DATA_COLLECTION = "data_collection"

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"

ALARM_AND_TIMER_ID_LENGTH = 42

# Icons
ICON_TOKEN = "mdi:form-textbox-password"
ICON_ALARMS = "mdi:alarm-multiple"
ICON_TIMERS = "mdi:timer-sand"
ICON_DO_NOT_DISTURB = "mdi:minus-circle"

# Device classes
BINARY_SENSOR_DEVICE_CLASS = "connectivity"

# Platforms
SENSOR = "sensor"
SWITCH = "switch"
PLATFORMS = [SENSOR, SWITCH]

# Services
SERVICE_REBOOT = "reboot_device"
SERVICE_DELETE_ALARM = "delete_alarm"
SERVICE_DELETE_TIMER = "delete_timer"
SERVICE_ATTR_ALARM_ID = "alarm_id"
SERVICE_ATTR_TIMER_ID = "timer_id"

# Configuration and options
CONF_ANDROID_ID = "android_id"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_MASTER_TOKEN = "master_token"

# Defaults
DEFAULT_NAME = "Google Home"

LABEL_ALARMS = "alarms"
LABEL_AVAILABLE = "available"
LABEL_TIMERS = "timers"
LABEL_DEVICE = "device"
LABEL_DO_NOT_DISTURB = "Do Not Disturb"

# DEVICE PORT
PORT = 8443

# API
API_ENDPOINT_ALARMS = "setup/assistant/alarms"
API_ENDPOINT_DELETE = "setup/assistant/alarms/delete"
API_ENDPOINT_REBOOT = "setup/reboot"
API_ENDPOINT_DO_NOT_DISTURB = "setup/assistant/notifications"
HEADER_CAST_LOCAL_AUTH = "cast-local-authorization-token"
HEADER_CONTENT_TYPE = "content-type"

# HEADERS
HEADERS = {
    HEADER_CAST_LOCAL_AUTH: "",
    HEADER_CONTENT_TYPE: "application/json",
}
TIMEOUT = 2  # Request Timeout in seconds

# TIMESTRINGS
TIME_STR_FORMAT = "%H:%M:%S"
DATETIME_STR_FORMAT = f"{DATE_STR_FORMAT} {TIME_STR_FORMAT}"

# API ERROR'S
API_RETURNED_UNKNOWN = "API returned unknown json structure"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
UPDATE_INTERVAL = 10  # sec

# JSON parameter values when retrieving information from devices
JSON_ALARM = "alarm"
JSON_TIMER = "timer"
JSON_NOTIFICATIONS_ENABLED = "notifications_enabled"

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
