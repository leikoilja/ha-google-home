"""Various types used in type hints."""
from typing import Iterable, List, Optional, Set, Tuple, TypedDict

from typing_extensions import Protocol

from homeassistant.helpers.entity import Entity


class AddEntitiesCallback(Protocol):
    """Protocol type for async_setup_entry callback"""

    def __call__(
        self, new_entities: Iterable[Entity], update_before_add: bool = False
    ) -> None:
        ...


class AlarmJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of alarm returned by Google Home API"""

    id: str
    fire_time: int
    label: Optional[str]
    recurrence: Optional[str]


class TimerJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of timer returned by Google Home API"""

    id: str
    fire_time: int
    original_duration: int
    label: Optional[str]


class GoogleHomeAlarmDict(TypedDict):
    """Typed dict representation of Google Home alarm"""

    alarm_id: str
    fire_time: int
    label: Optional[str]
    recurrence: Optional[str]


class GoogleHomeTimerDict(TypedDict):
    """Typed dict representation of Google Home time"""

    timer_id: str
    fire_time: int
    duration: str
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

    alarms: List[GoogleHomeAlarmDict]
    integration: str


class TimersAttributes(TypedDict):
    """Typed dict for timers attributes"""

    timers: List[GoogleHomeTimerDict]
    integration: str


class DeviceInfo(TypedDict):
    """Typed dict for device_info"""

    identifiers: Set[Tuple[str, str]]
    name: str
    manufacturer: str
