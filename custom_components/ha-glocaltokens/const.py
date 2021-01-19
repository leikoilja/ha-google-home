"""Constants for Google local authentication token fetching."""
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
DEFAULT_NAME = "GlocalToken"

# Access token only lives about 1 hour
SCAN_INTERVAL = 1800  # 30 mins

GLOCALTOKENS_DEVICE_NAME = "deviceName"
GLOCALTOKENS_TOKEN = "localAuthToken"


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
