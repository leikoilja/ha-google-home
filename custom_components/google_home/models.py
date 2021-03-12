"""Models for Google Home"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import (
    DATETIME_STR_FORMAT,
    FIRE_TIME,
    ID,
    LABEL,
    ORIGINAL_DURATION,
    RECURRENCE,
)


def convert_from_ms_to_s(timestamp: int) -> int:
    """Converts from milliseconds to seconds"""
    return round(timestamp / 1000)


class GoogleHomeDevice:
    """Local representation of Google Home device"""

    def __init__(
        self,
        name: str,
        auth_token: str,
        ip_address: Optional[str] = None,
        hardware: Optional[str] = None,
    ):
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        self.available = True
        self._timers: List[GoogleHomeTimer] = []
        self._alarms: List[GoogleHomeAlarm] = []

    def set_alarms(self, alarms: List[Dict[str, Any]]) -> None:
        """Stores alarms as GoogleHomeAlarm objects"""
        self._alarms = [
            GoogleHomeAlarm(
                alarm_id=alarm[ID],
                fire_time=alarm[FIRE_TIME],
                label=alarm.get(LABEL),
                recurrence=alarm.get(RECURRENCE),
            )
            for alarm in alarms
        ]

    def set_timers(self, timers: List[Dict[str, Any]]) -> None:
        """Stores timers as GoogleHomeTimer objects"""
        self._timers = [
            GoogleHomeTimer(
                timer_id=timer[ID],
                fire_time=timer[FIRE_TIME],
                duration=timer[ORIGINAL_DURATION],
                label=timer.get(LABEL),
            )
            for timer in timers
        ]

    def get_sorted_alarms(self) -> List[GoogleHomeAlarm]:
        """Returns alarms in a sorted order"""
        return sorted(self._alarms, key=lambda k: k.fire_time)

    def get_next_alarm(self) -> Optional[GoogleHomeAlarm]:
        """Returns next alarm"""
        alarms = self.get_sorted_alarms()
        return alarms[0] if alarms else None

    def get_sorted_timers(self) -> List[GoogleHomeTimer]:
        """Returns timers in a sorted order"""
        return sorted(self._timers, key=lambda k: k.fire_time)

    def get_next_timer(self) -> Optional[GoogleHomeTimer]:
        """Returns next alarm"""
        timers = self.get_sorted_timers()
        return timers[0] if timers else None


class GoogleHomeTimer:
    """Local representation of Google Home timer"""

    def __init__(
        self,
        timer_id: str,
        fire_time: int,
        duration: int,
        label: Optional[str],
    ) -> None:
        self.timer_id = timer_id
        self.duration = str(timedelta(seconds=convert_from_ms_to_s(duration)))
        self.fire_time = convert_from_ms_to_s(fire_time)
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()


class GoogleHomeAlarm:
    """Local representation of Google Home alarm"""

    def __init__(
        self,
        alarm_id: str,
        fire_time: int,
        label: Optional[str],
        recurrence: Optional[str],
    ) -> None:
        self.alarm_id = alarm_id
        self.recurrence = recurrence
        self.fire_time = convert_from_ms_to_s(fire_time)
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()
