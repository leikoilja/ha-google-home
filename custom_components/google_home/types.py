"""Various types used in type hints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, Union


class AlarmJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of alarm returned by Google Home API"""

    id: str
    fire_time: int
    status: int
    label: str | None
    recurrence: str | None


class TimerJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of timer returned by Google Home API"""

    id: str
    fire_time: int
    original_duration: int
    status: int
    label: str | None


class GoogleHomeAlarmDict(TypedDict):
    """Typed dict representation of Google Home alarm"""

    alarm_id: str
    fire_time: int
    local_time: str
    local_time_iso: str
    status: str
    label: str | None
    recurrence: str | None


class GoogleHomeTimerDict(TypedDict):
    """Typed dict representation of Google Home timer"""

    timer_id: str
    fire_time: int | None
    local_time: str | None
    local_time_iso: str | None
    duration: str
    status: str
    label: str | None


class DeviceAttributes(TypedDict):
    """Typed dict for device attributes"""

    device_id: str | None
    device_name: str
    auth_token: str | None
    ip_address: str | None
    available: bool


class AlarmsAttributes(TypedDict):
    """Typed dict for alarms attributes"""

    next_alarm_status: str
    alarm_volume: float
    alarms: list[GoogleHomeAlarmDict]


class TimersAttributes(TypedDict):
    """Typed dict for timers attributes"""

    next_timer_status: str
    timers: list[GoogleHomeTimerDict]


class ConfigFlowDict(TypedDict):
    """Typed dict for config flow handler"""

    username: str
    password: str
    master_token: str


JsonDict = Mapping[
    str,
    Union[bool, float, int, str, list[str], list[AlarmJsonDict], list[TimerJsonDict]],
]


class BTJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of BT items returned by Google Home API"""

    id: str
    mac_address: str
    device_class: int
    device_type: int
    rssi: int
    expected_profiles: int
    name: str | None


class GoogleHomeBTDeviceDict(TypedDict):
    """Typed dict representation of Google Home bluetooth device"""

    mac_address: str
    device_type: str
    rssi: int
    expected_profiles: int
    name: str | None


class BTDeviceAttributes(TypedDict):
    """Typed dict for BT device attributes"""

    bt_devices: list[GoogleHomeBTDeviceDict]
    integration: str


class EurekaAoghDict(TypedDict):
    """Typed dict for Aogh response in Eureka info"""

    aogh_api_version: str


class EurekaAudioDict(TypedDict):
    """Typed dict for Audio response in Eureka info"""

    digital: bool


class EurekaBuildInfoDict(TypedDict):
    """Typed dict for build_info response in Eureka info"""

    build_type: int
    cast_build_revision: str
    cast_control_version: int
    preview_channel_state: int
    release_track: str
    system_build_number: str


class EurekaDetailDict(TypedDict):
    """Typed dict for detail response in Eureka info"""

    icon_list: list[dict[str, int | str]]
    locale: dict[str, str]
    timezone: dict[str, str | int]


class EurekaDeviceInfoCapabilities(TypedDict):
    """Typed dict for capabilities response in Eureka info/device info"""

    aogh_supported: bool
    assistant_supported: bool
    audio_hdr_supported: bool
    audio_surround_mode_supported: bool
    ble_supported: bool
    bluetooth_audio_sink_supported: bool
    bluetooth_audio_source_supported: bool
    bluetooth_supported: bool
    cloud_groups_supported: bool
    cloudcast_supported: bool
    content_filters_supported: bool
    disable_google_dns_supported: bool
    display_supported: bool
    fdr_supported: bool
    hdmi_prefer_50hz_supported: bool
    hdmi_prefer_high_fps_supported: bool
    hotspot_supported: bool
    https_setup_supported: bool
    input_management_supported: bool
    keep_hotspot_until_connected_supported: bool
    multi_user_supported: bool
    multichannel_group_supported: bool
    multizone_supported: bool
    night_mode_supported: bool
    night_mode_supported_v2: bool
    opencast_supported: bool
    preview_channel_supported: bool
    reboot_supported: bool
    remote_ducking_supported: bool
    renaming_supported: bool
    set_network_supported: bool
    setup_supported: bool
    sleep_mode_supported: bool
    stats_supported: bool
    system_sound_effects_supported: bool
    ui_flipping_supported: bool
    user_eq_supported: bool
    wifi_auto_save_supported: bool
    wifi_regulatory_domain_locked: bool
    wifi_supported: bool


class EurekaDeviceInfo(TypedDict):
    """Typed dict for device info response in Eureka info"""

    # 4k_blocked skipped as typeddict does not want something starting with a number.
    capabilities: EurekaDeviceInfoCapabilities
    cloud_device_id: str
    factory_country_code: str
    hotspot_bssid: str
    local_authorization_token_hash: str
    mac_address: str
    model_name: str
    product_name: str
    public_key: str
    ssdp_udn: str
    uptime: float
    weave_device_id: str


class EurekaInfoDict(TypedDict):
    """Typed dict for Eureka info"""

    aogh: EurekaAoghDict
    audio: EurekaAudioDict
    build_info: EurekaBuildInfoDict
    detail: EurekaDetailDict
    device_info: EurekaDeviceInfo
    # Any of the below should be extracted into their own class if used.
    multizone: dict[str, float]
    name: str
    net: dict[str, bool | str]
    night_mode_params: dict[str, int | float | bool]
    opt_in: dict[str, bool | int]
    proxy: dict[str, str]
    settings: dict[str, int | str]
    setup: dict[str, str | int]
    sign: dict[str, str]
    user_eq: dict[str, str]
    version: str
    wifi: dict[str, str | bool | int]
