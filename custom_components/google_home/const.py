"""Constants for Google Home."""

from typing import Final

from homeassistant.util.dt import DATE_STR_FORMAT

# Base component constants
DOMAIN: Final = "google_home"
MANUFACTURER: Final = "Google Home"

CONF_UPDATE_INTERVAL: Final = "update_interval"
# Addresses of devices that mDNS can't find, for example on another network
CONF_KNOWN_HOSTS: Final = "known_hosts"
# IDs of the Google homes whose devices aren't added. Saved only when some are, so
# an entry without it, and a home the account joins later, has its devices added.
CONF_EXCLUDED_HOMES: Final = "excluded_homes"
# The form field that chooses the homes whose devices are added
CONF_HOMES: Final = "homes"
CONF_BLUETOOTH_TRACKING: Final = "bluetooth_tracking"
# Device IDs of speakers that don't scan for Bluetooth trackers
CONF_BLUETOOTH_EXCLUDED: Final = "bluetooth_excluded_speakers"
CONF_IRK: Final = "irk"
# The field that takes a tracked device's IRK or MAC address. It's saved as one of
# them.
CONF_IRK_OR_MAC: Final = "irk_or_mac"
SUBENTRY_BLUETOOTH_DEVICE: Final = "bluetooth_device"

ALARM_AND_TIMER_ID_LENGTH: Final = 42

# Platforms
SENSOR: Final = "sensor"
SWITCH: Final = "switch"
NUMBER: Final = "number"
BUTTON: Final = "button"
BINARY_SENSOR: Final = "binary_sensor"
DEVICE_TRACKER: Final = "device_tracker"
PLATFORMS: Final = [SENSOR, SWITCH, NUMBER, BUTTON, BINARY_SENSOR, DEVICE_TRACKER]

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

# The repair shown while polling is turned off in the entry's system options, and
# the docs that its text links to. Home Assistant shows a fixable repair's fix
# straight away, without a learn_more_url.
ISSUE_POLLING_DISABLED: Final = "polling_disabled"
POLLING_DOCS_URL: Final = (
    "https://ha-google-home.pages.dev/configuration/#turn-off-polling"
)

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
LABEL_TIMERS: Final = "timers"
LABEL_DEVICE: Final = "device"
LABEL_DO_NOT_DISTURB: Final = "Do Not Disturb"
LABEL_REBOOT: Final = "reboot"
LABEL_FIRMWARE_UPDATE: Final = "firmware update"
LABEL_WIFI_NETWORK: Final = "Wi-Fi network"
LABEL_WIFI_SIGNAL: Final = "Wi-Fi signal"

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
# The device's firmware versions, which also answer without a token. A display's
# system version is only here.
API_ENDPOINT_BUILD_INFO: Final = "setup/eureka_info?params=build_info"
# Without params, the info has whether the device has a firmware update waiting, which
# no params give. It also has the device's Wi-Fi network and signal strength, which are
# kept, and its location and IDs, which aren't.
API_ENDPOINT_UPDATE_INFO: Final = "setup/eureka_info"

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
# Around an alarm's or timer's fire time, its device is updated sooner than the update
# interval, if that's longer. First this many seconds after its fire time, also after a
# snooze. An update can start up to a second early. It still starts after the fire time
# rounded to the second, so up to half a second before the speaker's own; then the
# updates every ONSET_INTERVAL seconds follow.
FIRE_TIME_DELAY: Final = 1  # sec
# Then, while it still isn't ringing, every ONSET_INTERVAL seconds, until an update
# that starts at least ONSET_WINDOW seconds after its fire time. Rings were seen at the
# first update after the fire time, 2 to 9 seconds after it at a 10-second interval.
ONSET_INTERVAL: Final = 5  # sec
ONSET_WINDOW: Final = 30  # sec
# While it rings, every RINGING_INTERVAL seconds, until an update that starts at least
# RINGING_WINDOW seconds after its fire time. On one speaker that was tested, an alarm
# that nobody stopped rang for about an hour, and a timer for about 10 minutes.
RINGING_INTERVAL: Final = 10  # sec
RINGING_WINDOW: Final = 65 * 60  # sec
# Fetch Google's device list again this long after the last fetch, however often
# the devices are updated, to find devices added in or removed from the Google Home
# app and the address of a device that was offline. It's a request to Google, so not
# on every update.
FETCH_DEVICES_INTERVAL: Final = 20 * 60  # sec
# Remove a device from Home Assistant, with its entities, once this many home graphs
# in a row that Google answered with have lacked it. One home graph may miss a device
# that Google still has.
HOME_GRAPHS_BEFORE_REMOVAL: Final = 2
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
# Ask a device for its firmware version and whether it has an update at most this
# often, counted from the start of the last check. Firmware changes rarely.
FIRMWARE_CHECK_INTERVAL: Final = 20 * 60  # sec

# Bluetooth scans of the speakers, for Bluetooth tracking
API_ENDPOINT_BLUETOOTH_SCAN: Final = "setup/bluetooth/scan"
API_ENDPOINT_BLUETOOTH_RESULTS: Final = "setup/bluetooth/scan_results"
# Bluetooth tracking, in seconds unless noted. Each update asks every speaker for
# a scan of up to this long, and the next update reads its results and starts the
# next scan.
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
# A tracker shows each speaker's median signal strength over windows this long,
# for the speakers that heard the device in at least this many scans
BLUETOOTH_RSSI_WINDOW: Final = 300
BLUETOOTH_RSSI_MIN_SCANS: Final = 2

# JSON parameter values when retrieving information from devices
JSON_ALARM: Final = "alarm"
JSON_TIMER: Final = "timer"
JSON_NOTIFICATIONS_ENABLED: Final = "notifications_enabled"
JSON_ALARM_VOLUME: Final = "volume"
