"""Various types used in type hints."""
from typing import List, Mapping, Optional, Set, Tuple, TypedDict, Union


class AlarmJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of alarm returned by Google Home API"""

    id: str
    fire_time: int
    status: int
    label: Optional[str]
    recurrence: Optional[str]


class TimerJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of timer returned by Google Home API"""

    id: str
    fire_time: int
    original_duration: int
    status: int
    label: Optional[str]


class GoogleHomeAlarmDict(TypedDict):
    """Typed dict representation of Google Home alarm"""

    alarm_id: str
    fire_time: int
    local_time: str
    local_time_iso: str
    status: str
    label: Optional[str]
    recurrence: Optional[str]


class GoogleHomeTimerDict(TypedDict):
    """Typed dict representation of Google Home timer"""

    timer_id: str
    fire_time: Optional[int]
    local_time: Optional[str]
    local_time_iso: Optional[str]
    duration: str
    status: str
    label: Optional[str]


class DeviceAttributes(TypedDict):
    """Typed dict for device attributes"""

    device_name: str
    auth_token: Optional[str]
    ip_address: Optional[str]
    hardware: Optional[str]
    available: bool
    integration: str


class AlarmsAttributes(TypedDict):
    """Typed dict for alarms attributes"""

    next_alarm_status: str
    alarms: List[GoogleHomeAlarmDict]
    integration: str


class TimersAttributes(TypedDict):
    """Typed dict for timers attributes"""

    next_timer_status: str
    timers: List[GoogleHomeTimerDict]
    integration: str


class DeviceInfo(TypedDict):
    """Typed dict for device_info"""

    identifiers: Set[Tuple[str, str]]
    name: str
    manufacturer: str


class OptionsFlowDict(TypedDict):
    """Typed dict for options flow handler"""

    data_collection: bool


JsonDict = Mapping[
    str, Union[bool, int, str, List[str], List[AlarmJsonDict], List[TimerJsonDict]]
]
