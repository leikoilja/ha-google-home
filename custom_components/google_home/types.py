"""Various types used in type hints."""

from collections.abc import Mapping
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry


class AlarmJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of alarm returned by Google Home API."""

    id: str
    fire_time: int
    status: int
    label: str | None
    recurrence: str | None


class TimerJsonDict(TypedDict, total=False):
    """Typed dict for JSON representation of timer returned by Google Home API."""

    id: str
    fire_time: int
    original_duration: int
    remaining_duration: int
    status: int
    label: str | None


class GoogleHomeAlarmDict(TypedDict):
    """Typed dict representation of Google Home alarm."""

    alarm_id: str
    fire_time: int
    local_time: str
    local_time_iso: str
    status: str
    label: str | None
    recurrence: str | None


class GoogleHomeTimerDict(TypedDict):
    """Typed dict representation of Google Home timer."""

    timer_id: str
    fire_time: int | None
    local_time: str | None
    local_time_iso: str | None
    duration: str
    remaining: str | None
    status: str
    label: str | None


class DeviceAttributes(TypedDict):
    """Typed dict for device attributes."""

    device_id: str | None
    device_name: str
    auth_token: str | None
    ip_address: str | None
    available: bool


class AlarmsAttributes(TypedDict):
    """Typed dict for alarms attributes."""

    next_alarm_status: str
    alarm_volume: float
    alarms: list[GoogleHomeAlarmDict]


class TimersAttributes(TypedDict):
    """Typed dict for timers attributes."""

    next_timer_status: str
    timers: list[GoogleHomeTimerDict]


class OptionsFlowDict(TypedDict, total=False):
    """Typed dict for options flow handler."""

    update_interval: int
    known_hosts: list[str]


type JsonDict = Mapping[
    str,
    bool | float | int | str | list[str] | list[AlarmJsonDict] | list[TimerJsonDict],
]

type GoogleHomeConfigEntry = ConfigEntry[None]
