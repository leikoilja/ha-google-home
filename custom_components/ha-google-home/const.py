"""Constants for Google local authentication token fetching."""
# Base component constants
NAME = "Google local authentication token fetching (Glocaltokens)"
DOMAIN = "ha-google-home"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"
MANUFACTURER = "ha-google-home"

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
DEFAULT_NAME = "HA-Google-Home"

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
FIRE_TIME = "fire_time"
FIRE_TIME_IN_S = "fire_time_in_s"
DATE_TIME = "date_time"
LOCAL_TIME = "local_time"
DURATION = "duration"
ORIGINAL_DURATION = "original_duration"

# TIMESTRINGS
SHOW_TIME_ONLY = "%H:%M:%S"
SHOW_DATE_TIMEZONE = "%Y-%m-%dT%H:%M:%S.%fZ%Z"
SHOW_DATE_AND_TIME = "%Y-%m-%d %H:%M:%S"

# API ERROR'S
API_RETURNED_UNKNOWN = "API returned unknown json structure"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
SCAN_INTERVAL = 15  # Seconds

# JSON parameter values when retrieving information from devices
ALARMS = "alarm"
TIMERS = "timer"


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
