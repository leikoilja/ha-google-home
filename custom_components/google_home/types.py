"""Various types used in type hints."""
from __future__ import annotations

from typing import List, Mapping, TypedDict, Union


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


class GoogleHomeEurekaDict(TypedDict):
    """Typed dict representation of Google Home Eureka"""

    device_info: EurekaDeviceInfoDict


class EurekaDeviceInfoDict(TypedDict):
    """Typed dict representation of Eureka's Device Info"""

    # 4k_blocked: int
    capabilities: EurekaCompatibilityDict | None
    cloud_device_id: str | None
    factory_country_code: str | None
    hotspot_bssid: str | None
    local_authorization_token_hash: str | None
    mac_address: str | None
    manufacturer: str | None
    model_name: str | None
    product_name: str | None
    public_key: str | None
    ssdp_udn: str | None
    uptime: float | None
    weave_device_id: str | None


class EurekaCompatibilityDict(TypedDict):
    """Typed dict representation of Eureka's Device Info's compatibility table"""

    aogh_supported: bool | None
    assistant_supported: bool | None
    audio_hdr_supported: bool | None
    audio_surround_mode_supported: bool | None
    ble_supported: bool | None
    bluetooth_audio_sink_supported: bool | None
    bluetooth_audio_source_supported: bool | None
    bluetooth_supported: bool | None
    cloudcast_supported: bool | None
    content_filters_supported: bool | None
    disable_google_dns_supported: bool | None
    display_supported: bool | None
    fdr_supported: bool | None
    hdmi_prefer_50hz_supported: bool | None
    hdmi_prefer_high_fps_supported: bool | None
    hotspot_supported: bool | None
    https_setup_supported: bool | None
    input_management_supported: bool | None
    keep_hotspot_until_connected_supported: bool | None
    multi_user_supported: bool | None
    multichannel_group_supported: bool | None
    multizone_supported: bool | None
    night_mode_supported: bool | None
    night_mode_supported_v2: bool | None
    opencast_supported: bool | None
    preview_channel_supported: bool | None
    reboot_supported: bool | None
    remote_ducking_supported: bool | None
    renaming_supported: bool | None
    setup_supported: bool | None
    sleep_mode_supported: bool | None
    stats_supported: bool | None
    system_sound_effects_supported: bool | None
    ui_flipping_supported: bool | None
    user_eq_supported: bool | None
    wifi_auto_save_supported: bool | None
    wifi_supported: bool | None


class DeviceAttributes(TypedDict):
    """Typed dict for device attributes"""

    device_name: str
    auth_token: str | None
    ip_address: str | None
    hardware: str | None
    available: bool
    integration: str


class AlarmsAttributes(TypedDict):
    """Typed dict for alarms attributes"""

    next_alarm_status: str
    alarm_volume: float
    alarms: list[GoogleHomeAlarmDict]
    integration: str


class TimersAttributes(TypedDict):
    """Typed dict for timers attributes"""

    next_timer_status: str
    timers: list[GoogleHomeTimerDict]
    integration: str


class DeviceInfo(TypedDict):
    """Typed dict for device_info"""

    identifiers: set[tuple[str, str]]
    name: str
    manufacturer: str


class OptionsFlowDict(TypedDict):
    """Typed dict for options flow handler"""

    data_collection: bool


JsonCChildrenElem = Union[
    str,
    bool,
    float,
    int,
    EurekaCompatibilityDict,
]

JsonCChildrenDict = Mapping[str, JsonCChildrenElem]

JsonChildrenElem = Union[
    str,
    bool,
    float,
    int,
    JsonCChildrenDict,
]

JsonChildrenDict = Mapping[str, JsonChildrenElem]

JsonElem = Union[
    bool,
    int,
    float,
    str,
    List[str],
    List[AlarmJsonDict],
    List[TimerJsonDict],
    JsonChildrenDict,
]

JsonDict = Mapping[str, JsonElem]
