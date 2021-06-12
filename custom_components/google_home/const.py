"""Constants for Google Home."""
from __future__ import annotations

from typing import Final

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
ICON_ALARM_VOLUME_LOW: Final[str] = "mdi:volume-low"
ICON_ALARM_VOLUME_MID: Final[str] = "mdi:volume-medium"
ICON_ALARM_VOLUME_HIGH: Final[str] = "mdi:volume-high"
ICON_ALARM_VOLUME_OFF: Final[str] = "mdi:volume-off"

# Device classes
BINARY_SENSOR_DEVICE_CLASS: Final[str] = "connectivity"

# Platforms
SENSOR: Final[str] = "sensor"
SWITCH: Final[str] = "switch"
PLATFORMS: Final[list[str]] = [SENSOR, SWITCH]

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
GOOGLE_HOME_ALARM_DEFAULT_VALUE: Final[float] = 0

LABEL_ALARMS: Final[str] = "alarms"
LABEL_ALARM_VOLUME: Final[str] = "alarm_volume"
LABEL_AVAILABLE: Final[str] = "available"
LABEL_TIMERS: Final[str] = "timers"
LABEL_DEVICE: Final[str] = "device"
LABEL_DO_NOT_DISTURB: Final[str] = "Do Not Disturb"

# DEVICE PORT
PORT: Final[int] = 8443

# API
API_ENDPOINT_ALARMS: Final[str] = "setup/assistant/alarms"
API_ENDPOINT_ALARM_DELETE: Final[str] = "setup/assistant/alarms/delete"
API_ENDPOINT_ALARM_VOLUME: Final[str] = "setup/assistant/alarms/volume"
API_ENDPOINT_REBOOT: Final[str] = "setup/reboot"
API_ENDPOINT_DO_NOT_DISTURB: Final[str] = "setup/assistant/notifications"
API_ENDPOINT_EUREKA: Final[str] = "setup/eureka_info"

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
JSON_ALARM_VOLUME: Final[str] = "volume"
JSON_NOTIFICATIONS_ENABLED: Final[str] = "notifications_enabled"
JSON_EUREKA_DEVICE_INFO: Final[str] = "device_info"
JSON_EUREKA_CAPABILITIES: Final[str] = "capabilities"

# EUREKA
EUREKA_KEY_PARAMS = "params"
EUREKA_KEY_OPTIONS = "options"
EUREKA_PARAMS = (
    "version,audio,name,build_info,detail,device_info,net,wifi,setup,settings,"
    "opt_in,opencast,multizone,proxy,night_mode_params,user_eq,room_equalizer,"
    "sign,aogh,ultrasound,mesh "
)
EUREKA_OPTIONS = "detail"
EUREKA_JSON_DEVICE_INFO_4K_BLOCKED = "4k_blocked"
EUREKA_JSON_DEVICE_INFO_CAPABILITIES = "capabilities"
EUREKA_JSON_DEVICE_INFO_CLOUD_DEVICE_ID = "cloud_device_id"
EUREKA_JSON_DEVICE_INFO_FACTORY_COUNTRY_CODE = "factory_country_code"
EUREKA_JSON_DEVICE_INFO_HOTSPOT_BSSID = "hotspot_bssid"
EUREKA_JSON_DEVICE_INFO_LATH = (
    "local_authorization_token_hash"  # Local Authorisation token hash
)
EUREKA_JSON_DEVICE_INFO_MAC_ADDRESS = "mac_address"
EUREKA_JSON_DEVICE_INFO_MANUFACTURER = "manufacturer"
EUREKA_JSON_DEVICE_INFO_MODEL_NAME = "model_name"
EUREKA_JSON_DEVICE_INFO_PRODUCT_NAME = "product_name"
EUREKA_JSON_DEVICE_INFO_PUBLIC_KEY = "public_key"
EUREKA_JSON_DEVICE_INFO_SSDP_UDN = "ssdp_udn"
EUREKA_JSON_DEVICE_INFO_UMA_CLIENT_ID = "uma_client_id"
EUREKA_JSON_DEVICE_INFO_UPTIME = "uptime"
EUREKA_JSON_DEVICE_INFO_WEAVE_DEVICE_ID = "weave_device_id"
EUREKA_JSON_DINFO_CAPABILITIES_AOGH = "aogh_supported"
EUREKA_JSON_DINFO_CAPABILITIES_ASSISTANT = "assistant_supported"
EUREKA_JSON_DINFO_CAPABILITIES_AUDIO_HDR = "audio_hdr_supported"
EUREKA_JSON_DINFO_CAPABILITIES_AUDIO_SURROUND = "audio_surround_mode_supported"
EUREKA_JSON_DINFO_CAPABILITIES_BLE = "ble_supported"
EUREKA_JSON_DINFO_CAPABILITIES_BASK = "bluetooth_audio_sink_supported"
EUREKA_JSON_DINFO_CAPABILITIES_BASS = "bluetooth_audio_source_supported"
EUREKA_JSON_DINFO_CAPABILITIES_BT = "bluetooth_supported"
EUREKA_JSON_DINFO_CAPABILITIES_CLOUDCAST = "cloudcast_supported"
EUREKA_JSON_DINFO_CAPABILITIES_CFILTERS = "content_filters_supported"
EUREKA_JSON_DINFO_CAPABILITIES_DISPLAY = "display_supported"
EUREKA_JSON_DINFO_CAPABILITIES_FDR = "fdr_supported"
EUREKA_JSON_DINFO_CAPABILITIES_HDMI_50HZ = "hdmi_prefer_50hz_supported"
EUREKA_JSON_DINFO_CAPABILITIES_HDMI_HIGH_FPS = "hdmi_prefer_high_fps_supported"
EUREKA_JSON_DINFO_CAPABILITIES_HOTSPOT = "hotspot_supported"
EUREKA_JSON_DINFO_CAPABILITIES_HTTPS_SETUP = "https_setup_supported"
EUREKA_JSON_DINFO_CAPABILITIES_INPUT_MANAGEMENT = "input_management_supported"
EUREKA_JSON_DINFO_CAPABILITIES_KHUC = "keep_hotspot_until_connected_supported"
EUREKA_JSON_DINFO_CAPABILITIES_MUSER = "multi_user_supported"
EUREKA_JSON_DINFO_CAPABILITIES_MCHANNEL_GROUP = "multichannel_group_supported"
EUREKA_JSON_DINFO_CAPABILITIES_MZONE = "multizone_supported"
EUREKA_JSON_DINFO_CAPABILITIES_NIGHT_MODE = "night_mode_supported"
EUREKA_JSON_DINFO_CAPABILITIES_NIGHT_MODE_V2 = "night_mode_supported_v2"
EUREKA_JSON_DINFO_CAPABILITIES_OPENCAST = "opencast_supported"
EUREKA_JSON_DINFO_CAPABILITIES_PREVIEW_CHANNEL = "preview_channel_supported"
EUREKA_JSON_DINFO_CAPABILITIES_REBOOT = "reboot_supported"
EUREKA_JSON_DINFO_CAPABILITIES_REMOTE_DUCKING = "remote_ducking_supported"
EUREKA_JSON_DINFO_CAPABILITIES_SEPP_TTS_VOLUME = "separate_tts_volume_supported"
EUREKA_JSON_DINFO_CAPABILITIES_SETUP = "setup_supported"
EUREKA_JSON_DINFO_CAPABILITIES_SLEEP_MODE = "sleep_mode_supported"
EUREKA_JSON_DINFO_CAPABILITIES_STATS = "stats_supported"
EUREKA_JSON_DINFO_CAPABILITIES_SYSTEM_SOUND_FX = "system_sound_effects_supported"
EUREKA_JSON_DINFO_CAPABILITIES_USER_EQUALIZER = "user_eq_supported"
EUREKA_JSON_DINFO_CAPABILITIES_WIFI_AUTO_SAVE = "wifi_auto_save_supported"
EUREKA_JSON_DINFO_CAPABILITIES_WIFI_REG_DOMAIN_LCK = "wifi_regulatory_domain_locked"
EUREKA_JSON_DINFO_CAPABILITIES_WIFI_SUPPORTED = "wifi_supported"
EUREKA_JSON_DEVICE_INFO = [
    EUREKA_JSON_DEVICE_INFO_4K_BLOCKED,
    EUREKA_JSON_DEVICE_INFO_CAPABILITIES,
    EUREKA_JSON_DEVICE_INFO_CLOUD_DEVICE_ID,
    EUREKA_JSON_DEVICE_INFO_FACTORY_COUNTRY_CODE,
    EUREKA_JSON_DEVICE_INFO_HOTSPOT_BSSID,
    EUREKA_JSON_DEVICE_INFO_LATH,
    EUREKA_JSON_DEVICE_INFO_MAC_ADDRESS,
    EUREKA_JSON_DEVICE_INFO_MANUFACTURER,
    EUREKA_JSON_DEVICE_INFO_MODEL_NAME,
    EUREKA_JSON_DEVICE_INFO_PRODUCT_NAME,
    EUREKA_JSON_DEVICE_INFO_PUBLIC_KEY,
    EUREKA_JSON_DEVICE_INFO_SSDP_UDN,
    EUREKA_JSON_DEVICE_INFO_UMA_CLIENT_ID,
    EUREKA_JSON_DEVICE_INFO_UPTIME,
    EUREKA_JSON_DEVICE_INFO_WEAVE_DEVICE_ID,
]
EUREKA_JSON_DINFO_CAPABILITIES = [
    EUREKA_JSON_DINFO_CAPABILITIES_AOGH,
    EUREKA_JSON_DINFO_CAPABILITIES_ASSISTANT,
    EUREKA_JSON_DINFO_CAPABILITIES_AUDIO_HDR,
    EUREKA_JSON_DINFO_CAPABILITIES_AUDIO_SURROUND,
    EUREKA_JSON_DINFO_CAPABILITIES_BLE,
    EUREKA_JSON_DINFO_CAPABILITIES_BASK,
    EUREKA_JSON_DINFO_CAPABILITIES_BASS,
    EUREKA_JSON_DINFO_CAPABILITIES_BT,
    EUREKA_JSON_DINFO_CAPABILITIES_CLOUDCAST,
    EUREKA_JSON_DINFO_CAPABILITIES_CFILTERS,
    EUREKA_JSON_DINFO_CAPABILITIES_DISPLAY,
    EUREKA_JSON_DINFO_CAPABILITIES_FDR,
    EUREKA_JSON_DINFO_CAPABILITIES_HDMI_50HZ,
    EUREKA_JSON_DINFO_CAPABILITIES_HDMI_HIGH_FPS,
    EUREKA_JSON_DINFO_CAPABILITIES_HOTSPOT,
    EUREKA_JSON_DINFO_CAPABILITIES_HTTPS_SETUP,
    EUREKA_JSON_DINFO_CAPABILITIES_INPUT_MANAGEMENT,
    EUREKA_JSON_DINFO_CAPABILITIES_KHUC,
    EUREKA_JSON_DINFO_CAPABILITIES_MUSER,
    EUREKA_JSON_DINFO_CAPABILITIES_MCHANNEL_GROUP,
    EUREKA_JSON_DINFO_CAPABILITIES_MZONE,
    EUREKA_JSON_DINFO_CAPABILITIES_NIGHT_MODE,
    EUREKA_JSON_DINFO_CAPABILITIES_NIGHT_MODE_V2,
    EUREKA_JSON_DINFO_CAPABILITIES_OPENCAST,
    EUREKA_JSON_DINFO_CAPABILITIES_PREVIEW_CHANNEL,
    EUREKA_JSON_DINFO_CAPABILITIES_REBOOT,
    EUREKA_JSON_DINFO_CAPABILITIES_REMOTE_DUCKING,
    EUREKA_JSON_DINFO_CAPABILITIES_SEPP_TTS_VOLUME,
    EUREKA_JSON_DINFO_CAPABILITIES_SETUP,
    EUREKA_JSON_DINFO_CAPABILITIES_SLEEP_MODE,
    EUREKA_JSON_DINFO_CAPABILITIES_STATS,
    EUREKA_JSON_DINFO_CAPABILITIES_SYSTEM_SOUND_FX,
    EUREKA_JSON_DINFO_CAPABILITIES_USER_EQUALIZER,
    EUREKA_JSON_DINFO_CAPABILITIES_WIFI_AUTO_SAVE,
    EUREKA_JSON_DINFO_CAPABILITIES_WIFI_REG_DOMAIN_LCK,
    EUREKA_JSON_DINFO_CAPABILITIES_WIFI_SUPPORTED,
]

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
