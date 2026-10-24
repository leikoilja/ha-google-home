"""Constants for Google Home."""

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
# Addresses of devices that mDNS can't find, for example on another network
CONF_KNOWN_HOSTS: Final = "known_hosts"
CONF_BLUETOOTH_TRACKING: Final = "bluetooth_tracking"
# Device IDs of speakers that don't scan for Bluetooth trackers
CONF_BLUETOOTH_EXCLUDED: Final = "bluetooth_excluded_speakers"
CONF_IRK: Final = "irk"
SUBENTRY_BLUETOOTH_DEVICE: Final = "bluetooth_device"

DATA_CLIENT: Final = "client"
DATA_COORDINATOR: Final = "coordinator"
DATA_BLUETOOTH: Final = "bluetooth"
# The Bluetooth settings the entry was set up with, to reload when they change
DATA_BLUETOOTH_CONFIG: Final = "bluetooth_config"

ALARM_AND_TIMER_ID_LENGTH: Final = 42

# Icons
ICON_TOKEN: Final = "mdi:form-textbox-password"
ICON_ALARMS: Final = "mdi:alarm-multiple"
ICON_TIMERS: Final = "mdi:timer-sand"
ICON_DO_NOT_DISTURB: Final = "mdi:minus-circle"
ICON_ALARM_VOLUME_LOW: Final = "mdi:volume-low"
ICON_ALARM_VOLUME_MID: Final = "mdi:volume-medium"
ICON_ALARM_VOLUME_HIGH: Final = "mdi:volume-high"
ICON_ALARM_VOLUME_OFF: Final = "mdi:volume-off"

# Platforms
SENSOR: Final = "sensor"
SWITCH: Final = "switch"
NUMBER: Final = "number"
BUTTON: Final = "button"
DEVICE_TRACKER: Final = "device_tracker"
PLATFORMS: Final = [SENSOR, SWITCH, NUMBER, BUTTON, DEVICE_TRACKER]

# Services
SERVICE_REBOOT: Final = "reboot_device"
SERVICE_DELETE_ALARM: Final = "delete_alarm"
SERVICE_DELETE_TIMER: Final = "delete_timer"
SERVICE_DELETE_ALL_ALARMS: Final = "delete_all_alarms"
SERVICE_DELETE_ALL_TIMERS: Final = "delete_all_timers"
SERVICE_REFRESH: Final = "refresh_devices"
SERVICE_ATTR_ALARM_ID: Final = "alarm_id"
SERVICE_ATTR_SKIP_REFRESH: Final = "skip_refresh"
SERVICE_ATTR_TIMER_ID: Final = "timer_id"

# Configuration and options
CONF_ANDROID_ID: Final = "android_id"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_MASTER_TOKEN: Final = "master_token"
CONF_OAUTH_TOKEN: Final = "oauth_token"

# Defaults
# Titles of entries whose Google account is unknown, by how they signed in
MASTER_TOKEN_TITLE: Final = f"{MANUFACTURER} (master_token)"
BROWSER_TITLE: Final = f"{MANUFACTURER} (browser)"
GOOGLE_HOME_ALARM_DEFAULT_VALUE: Final = 0

LABEL_ALARMS: Final = "alarms"
LABEL_ALARM_VOLUME: Final = "alarm volume"
LABEL_AVAILABLE: Final = "available"
LABEL_TIMERS: Final = "timers"
LABEL_DEVICE: Final = "device"
LABEL_DO_NOT_DISTURB: Final = "Do Not Disturb"
LABEL_REBOOT: Final = "reboot"

# DEVICE PORT
PORT: Final = 8443

# API
API_ENDPOINT_ALARMS: Final = "setup/assistant/alarms"
API_ENDPOINT_ALARM_DELETE: Final = "setup/assistant/alarms/delete"
API_ENDPOINT_ALARM_VOLUME: Final = "setup/assistant/alarms/volume"
API_ENDPOINT_REBOOT: Final = "setup/reboot"
API_ENDPOINT_DO_NOT_DISTURB: Final = "setup/assistant/notifications"
API_ENDPOINT_BLUETOOTH_SCAN: Final = "setup/bluetooth/scan"
API_ENDPOINT_BLUETOOTH_RESULTS: Final = "setup/bluetooth/scan_results"
# Answers without a local auth token, so it identifies a known host
API_ENDPOINT_EUREKA_INFO: Final = "setup/eureka_info?params=name,device_info"

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
# While a device has no IP address, fetch Google's device list again every this
# many updates. It's a request to Google, so not on every update.
FETCH_DEVICES_EVERY: Final = 10

# Bluetooth tracking, in seconds unless noted. Each scan lasts until the next
# update, which reads its results and starts the next scan.
BLUETOOTH_SCAN_INTERVAL: Final = 30
# Results read later than this after their scan started are discarded
BLUETOOTH_MAX_RESULT_AGE: Final = 45
# A longer gap between scans breaks a speaker's unbroken coverage
BLUETOOTH_MAX_SCAN_GAP: Final = 15
# A tracked device is home this long after the start of a scan that heard it,
# and away once every speaker has scanned this long without hearing it
BLUETOOTH_PRESENCE_WINDOW: Final = 90
# Weaker sightings are ignored: a phone away from home was once heard at -83
BLUETOOTH_MIN_RSSI: Final = -80  # dBm
# While the speakers can't tell whether a tracked device is home, its tracker
# keeps its last state this long, then shows unavailable. A speaker that has
# kept trackers from showing away this long is named in a warning.
BLUETOOTH_UNCERTAIN_LIMIT: Final = 300

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
