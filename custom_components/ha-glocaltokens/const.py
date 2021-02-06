"""Constants for Google local authentication token fetching."""
from datetime import timedelta

# Base component constants
NAME = "Google local authentication token fetching (Glocaltokens)"
DOMAIN = "glocaltokens"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"
MANUFACTURER = "Glocaltokens"

ATTRIBUTION = "json"
ISSUE_URL = "https://github.com/leikoilja/ha-glocaltokens/issues"

# Icons
ICON = "mdi:form-textbox-password"
ICON_ALARMS = "mdi:alarm-multiple"

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
DEFAULT_NAME = "GlocalHome"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
TIME_BETWEEN_UPDATES = timedelta(seconds=15) # Every 15 secs.

GLOCALTOKENS_DEVICE_NAME = "deviceName"
GLOCALTOKENS_TOKEN = "localAuthToken"
GLOCALTOKENS_ALARMS = "alarm"
GLOCALTOKENS_TIMERS = "timer"


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
