"""Constants for Google Home."""
from homeassistant.util.dt import DATE_STR_FORMAT

# Base component constants
NAME = "Google Home community driven integration"
DOMAIN = "google_home"
DOMAIN_DATA = f"{DOMAIN}_data"
MANUFACTURER = "google_home"

ATTRIBUTION = "json"
ISSUE_URL = "https://github.com/leikoilja/ha-google-home/issues"

# Icons
ICON_TOKEN = "mdi:form-textbox-password"
ICON_ALARMS = "mdi:alarm-multiple"
ICON_TIMERS = "mdi:timer-sand"

# Device classes
BINARY_SENSOR_DEVICE_CLASS = "connectivity"

# Platforms
SENSOR = "sensor"
PLATFORMS = [SENSOR]

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

# DEVICE PORT
PORT = 8443

# API
API_ENDPOINT_ALARMS = "setup/assistant/alarms"
HEADER_CAST_LOCAL_AUTH = "cast-local-authorization-token"
HEADER_CONTENT_TYPE = "content-type"

# HEADERS
HEADERS = {
    HEADER_CAST_LOCAL_AUTH: "",
    HEADER_CONTENT_TYPE: "application/json; charset=UTF-8",
}
TIMEOUT = 10  # Request Timeout in seconds

# TIMERS & ALARMS ATTRIBUTE NAMES
ID = "id"
LABEL = "label"
RECURRENCE = "recurrence"
FIRE_TIME = "fire_time"
ORIGINAL_DURATION = "original_duration"

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

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
