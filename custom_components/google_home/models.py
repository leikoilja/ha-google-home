from datetime import timedelta
import json
from typing import Optional

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import (
    DATETIME_STR_FORMAT,
    DOMAIN,
    FIRE_TIME,
    ID,
    LABEL,
    ORIGINAL_DURATION,
    RECURRENCE,
)


def convert_from_ms_to_s(timestamp):
    return round(timestamp / 1000)


class GoogleHomeDevice:
    """Local representation of Google Home device"""

    def __init__(
        self,
        name: str,
        token: str,
        ip_address: Optional[str] = None,
        hardware: Optional[str] = None,
    ) -> None:
        self.name = name
        self.token = token
        self.ip_address = ip_address
        self.hardware = hardware
        self.available = True
        self._timers = []
        self._alarms = []
        self.integration = DOMAIN

    def set_alarms(self, alarms):
        """Stores alarms as GoogleHomeAlarm objects"""
        self._alarms = [
            GoogleHomeAlarm(
                _id=alarm[ID],
                fire_time=alarm[FIRE_TIME],
                label=alarm.get(LABEL),
                recurrence=alarm.get(RECURRENCE),
            )
            for alarm in alarms
        ]

    def set_timers(self, timers):
        """Stores timers as GoogleHomeTimer objects"""
        self._timers = [
            GoogleHomeTimer(
                _id=timer[ID],
                fire_time=timer[FIRE_TIME],
                duration=timer[ORIGINAL_DURATION],
                label=timer.get(LABEL),
            )
            for timer in timers
        ]

    def get_alarms(self):
        """Returns alarms in a sorted order"""
        return sorted(self._alarms, key=lambda k: k.fire_time)

    def get_next_alarm(self):
        """Returns next alarm"""
        alarms = self.get_alarms()
        return alarms[0] if alarms else None

    def get_alarms_as_dict(self):
        """Returns list of alarms as nested dictionary"""
        alarms = self.get_alarms()
        return self.as_dict(alarms)

    def get_timers(self):
        """Returns timers in a sorted order"""
        return sorted(self._timers, key=lambda k: k.fire_time)

    def get_next_timer(self):
        """Returns next alarm"""
        timers = self.get_timers()
        return timers[0] if timers else None

    def get_timers_as_dict(self):
        """Returns list of timers as nested dictionary"""
        timers = self.get_timers()
        return self.as_dict(timers)

    @staticmethod
    def as_dict(obj, flat=False):
        """Returns object representation as dictionary
        flat=True removes nested objects like list of alarms/timers"""
        _dict = json.loads(json.dumps(obj, default=lambda o: o.__dict__))
        if flat:
            _dict.pop("_timers")
            _dict.pop("_alarms")
        return _dict


class GoogleHomeTimer:
    """Local representation of Google Home timer"""

    def __init__(
        self,
        _id,
        fire_time,
        duration,
        label,
    ) -> None:
        self._id = _id
        self.duration = str(timedelta(seconds=convert_from_ms_to_s(duration)))
        self.fire_time = convert_from_ms_to_s(fire_time)
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()


class GoogleHomeAlarm:
    """Local representation of Google Home alarm"""

    def __init__(self, _id, fire_time, label, recurrence) -> None:
        self._id = _id
        self.recurrence = recurrence
        self.fire_time = convert_from_ms_to_s(fire_time)
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()
