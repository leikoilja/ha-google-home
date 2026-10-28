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

DATA_CLIENT: Final = "client"
DATA_COORDINATOR: Final = "coordinator"

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
PLATFORMS: Final = [SENSOR, SWITCH, NUMBER, BUTTON]

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
# Answers without a local auth token, so it identifies a known host and shows
# whether a device whose alarms answer "not found" has Google Assistant
API_ENDPOINT_EUREKA_INFO: Final = "setup/eureka_info?params=name,device_info"

# HEADERS
HEADER_CAST_LOCAL_AUTH: Final = "cast-local-authorization-token"
HEADER_CONTENT_TYPE: Final = "content-type"

# How long a device has to answer a request, in seconds. A busy device can take
# more than 2 seconds.
TIMEOUT: Final = 5
# A device's alarms and timers sensors, Do Not Disturb switch and alarm volume are
# unavailable once it hasn't answered this many updates in a row. In logs at a
# 10-second interval, speakers that restarted at night missed 2 or 3.
UNANSWERED_UPDATES: Final = 5

# TIMESTRINGS
TIME_STR_FORMAT: Final = "%H:%M:%S"
DATETIME_STR_FORMAT: Final = f"{DATE_STR_FORMAT} {TIME_STR_FORMAT}"

# Access token only lives about 1 hour
# Update often to fetch timers in timely manner
UPDATE_INTERVAL: Final = 15  # sec
# Fetch Google's device list again this long after the last fetch, however often
# the devices are updated, to find devices added in or removed from the Google Home
# app and the address of a device that was offline. It's a request to Google, so not
# on every update.
FETCH_DEVICES_INTERVAL: Final = 20 * 60  # sec
# While Google's device list is unknown, wait at least this many seconds after the start
# of a fetch that failed before fetching it again: the first value after one failure,
# the next after two in a row, and so on, staying at the last. It's never longer than
# the fetch interval, so a retry is never due later than the scheduled fetch would be.
FETCH_RETRY_DELAYS: Final = (1 * 60, 2 * 60, 5 * 60, 10 * 60, FETCH_DEVICES_INTERVAL)
# The mDNS service that Google Cast devices announce themselves with
CAST_SERVICE_TYPE: Final = "_googlecast._tcp.local."
# How long to wait for an mDNS lookup of a Cast device that isn't cached
CAST_LOOKUP_TIMEOUT: Final = 3000  # ms
# Fetch Google's device list this long after mDNS first finds a Cast device that the
# list doesn't have, as the device may have just been added in the Google Home app.
# Devices found meanwhile share the fetch, and a new device gets time to appear in the
# list.
FOUND_DEVICE_FETCH_DELAY: Final = 30  # sec
# Fetch the list for devices that mDNS found at most this often, counted from the
# start of the last such fetch. Other fetches don't count, and don't wait for it.
FOUND_DEVICE_FETCH_GAP: Final = 5 * 60  # sec
# A device's alarms must still answer "not found" this long after they first did
# before its device info can show that it has none: a device that is starting
# answers "not found" for a while. Also the least time between device info requests
# to a device whose alarms keep answering "not found" but which reports Google
# Assistant or gives no clear answer.
SUPPORT_CHECK_DELAY: Final = 10 * 60  # sec

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
