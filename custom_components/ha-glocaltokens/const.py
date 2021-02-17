"""Constants for Google local authentication token fetching."""
# Base component constants
NAME = "Google local authentication token fetching (Glocaltokens)"
DOMAIN = "ha-glocaltokens"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"
MANUFACTURER = "ha-glocaltokens"

ATTRIBUTION = "json"
ISSUE_URL = "https://github.com/leikoilja/ha-glocaltokens/issues"

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
DEFAULT_NAME = "HA-GlocalTokens"

# API
PORT = 8443
API_ENDPOINT_ALARMS = "setup/assistant/alarms"
HEADER_CAST_LOCAL_AUTH = "cast-local-authorization-token"
HEADER_CONTENT_TYPE = "content-type"

HEADERS = {
    HEADER_CAST_LOCAL_AUTH: "",
    HEADER_CONTENT_TYPE: "application/json; charset=UTF-8",
}

# TIMERS & ALARMS ATTRIBUTES
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

# API Error
API_RETURNED_UNKNOWN = "API returned unknown json structure"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
SCAN_INTERVAL = 15  # Seconds

DEVICE_NAME = "device_name"
DEVICE_IP = "ip"
DEVICE_PORT = "port"
TOKEN = "local_auth_token"
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
