"""Models for Google Home."""

from datetime import timedelta
from enum import Enum
from http import HTTPStatus
import logging
import math
import sys

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import (
    DATETIME_STR_FORMAT,
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    UNANSWERED_UPDATES,
)
from .types import (
    AlarmJsonDict,
    GoogleHomeAlarmDict,
    GoogleHomeTimerDict,
    TimerJsonDict,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def convert_from_ms_to_s(timestamp: int) -> int:
    """Convert from milliseconds to seconds."""
    return round(timestamp / 1000)


class GoogleHomeDevice:
    """Local representation of Google Home device."""

    def __init__(
        self,
        device_id: str,
        name: str,
        auth_token: str | None,
        ip_address: str | None = None,
        hardware: str | None = None,
        cloud_device_id: str | None = None,
    ):
        """Create Google Home device object."""
        self.device_id = device_id
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        # Google's ID for the device, which it also reports locally
        self.cloud_device_id = cloud_device_id.lower() if cloud_device_id else None
        # Whether the last request for alarms, settings or a reboot succeeded. Its
        # alarms, timers and settings entities are added only then.
        self.available = True
        # Whether its alarms, or else its info, answered 200 at the last update: the
        # device sensor's available attribute
        self.reachable = True
        # Whether the device has no alarms, timers and settings, so it isn't asked
        # for them until the integration is loaded again
        self.alarms_unsupported = False
        # The HTTP status of the last request to each endpoint, if it got an answer.
        # Kept apart by whether it was scheduled, so an action that gets an answer
        # while an update runs doesn't replace the one the update checks.
        self.statuses: dict[tuple[str, bool], int] = {}
        # When to check again whether a device whose alarms answered "not found" has
        # any, if they still do then
        self.support_check_at: float | None = None
        # Updates in a row whose alarms request, or info request if it has no alarms,
        # the device didn't answer
        self.unanswered_updates = 0
        self._do_not_disturb = False
        self._alarm_volume = GOOGLE_HOME_ALARM_DEFAULT_VALUE
        self._timers: list[GoogleHomeTimer] = []
        self._alarms: list[GoogleHomeAlarm] = []

    def count_answer(self, status: int | None) -> bool:
        """Count the answer to this update's request, and return whether there was one.

        The status is that of its alarms request, or of its info request if it has no
        alarms, and None if it didn't answer. Once it hasn't answered
        UNANSWERED_UPDATES in a row, its entities are unavailable until an answer,
        even an error, other than "not found". A speaker that is starting answers that
        for a while: it ends a shorter run, but doesn't bring back what a run made
        unavailable.
        """
        unavailable = self.unanswered_updates >= UNANSWERED_UPDATES
        if status is None:
            self.unanswered_updates += 1
            if self.unanswered_updates == UNANSWERED_UPDATES:
                _LOGGER.info(
                    "%s didn't answer %d updates in a row. Its entities are "
                    'unavailable until it answers with something other than "not '
                    'found".',
                    self.name,
                    UNANSWERED_UPDATES,
                )
            return False
        if unavailable and status == HTTPStatus.NOT_FOUND:
            return True
        if unavailable and self.alarms_unsupported:
            _LOGGER.info(
                "%s answers again. Its device sensor and reboot button are available; "
                "it has no alarms, timers or settings.",
                self.name,
            )
        elif unavailable:
            _LOGGER.info("%s answers again. Its entities are available.", self.name)
        self.unanswered_updates = 0
        return True

    def set_alarms(self, alarms: list[AlarmJsonDict]) -> None:
        """Store alarms as GoogleHomeAlarm objects."""
        self._alarms = [
            GoogleHomeAlarm(
                alarm_id=alarm["id"],
                fire_time=alarm["fire_time"],
                status=alarm["status"],
                label=alarm.get("label"),
                recurrence=alarm.get("recurrence"),
            )
            for alarm in alarms
        ]

    def set_timers(self, timers: list[TimerJsonDict]) -> None:
        """Store timers as GoogleHomeTimer objects."""
        self._timers = [
            GoogleHomeTimer(
                timer_id=timer["id"],
                fire_time=timer.get("fire_time"),
                duration=timer["original_duration"],
                remaining=timer.get("remaining_duration"),
                status=timer["status"],
                label=timer.get("label"),
            )
            for timer in timers
        ]

    def remove_alarms_and_timers(self, ids: list[str]) -> None:
        """Remove the alarms and timers with these IDs."""
        self._alarms = [alarm for alarm in self._alarms if alarm.alarm_id not in ids]
        self._timers = [timer for timer in self._timers if timer.timer_id not in ids]

    def get_sorted_alarms(self) -> list[GoogleHomeAlarm]:
        """Return alarms in a sorted order. Inactive & missed alarms are at the end."""
        return sorted(
            self._alarms,
            key=lambda k: (
                k.fire_time
                if k.status
                not in {GoogleHomeAlarmStatus.INACTIVE, GoogleHomeAlarmStatus.MISSED}
                else k.fire_time + sys.maxsize
            ),
        )

    def get_next_alarm(self) -> GoogleHomeAlarm | None:
        """Return next alarm."""
        alarms = self.get_sorted_alarms()
        return alarms[0] if alarms else None

    def get_sorted_timers(self) -> list[GoogleHomeTimer]:
        """Return timers in a sorted order. If timer is paused, put it in the end."""
        return sorted(
            self._timers,
            key=lambda k: k.fire_time if k.fire_time is not None else sys.maxsize,
        )

    def get_next_timer(self) -> GoogleHomeTimer | None:
        """Return next alarm."""
        timers = self.get_sorted_timers()
        return timers[0] if timers else None

    def set_do_not_disturb(self, status: bool) -> None:
        """Set Do Not Disturb status."""
        self._do_not_disturb = status

    def get_do_not_disturb(self) -> bool:
        """Return Do Not Disturb status."""
        return self._do_not_disturb

    def set_alarm_volume(self, volume: int) -> None:
        """Set Alarm Volume status."""
        self._alarm_volume = volume

    def get_alarm_volume(self) -> int:
        """Return Alarm Volume status."""
        return self._alarm_volume


class GoogleHomeTimer:
    """Local representation of Google Home timer."""

    def __init__(
        self,
        timer_id: str,
        fire_time: int | None,
        duration: int,
        remaining: int | None,
        status: int,
        label: str | None,
    ) -> None:
        """Create Google Home Timer object."""
        self.timer_id = timer_id
        self.duration = str(timedelta(seconds=convert_from_ms_to_s(duration)))
        self.status = GoogleHomeTimerStatus(status)
        self.label = label
        # Only for a paused timer: a running one has a fire time, and the time left it
        # had at the last update would be out of date. Rounded up, as the speaker shows it.
        self.remaining = (
            str(timedelta(seconds=math.ceil(remaining / 1000)))
            if remaining is not None and self.status is GoogleHomeTimerStatus.PAUSED
            else None
        )

        if fire_time is None:
            self.fire_time = None
            self.local_time = None
            self.local_time_iso = None
        else:
            self.fire_time = convert_from_ms_to_s(fire_time)
            dt_utc = utc_from_timestamp(self.fire_time)
            dt_local = as_local(dt_utc)
            self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
            self.local_time_iso = dt_local.isoformat()

    def as_dict(self) -> GoogleHomeTimerDict:
        """Return typed dict representation."""
        return {
            "timer_id": self.timer_id,
            "fire_time": self.fire_time,
            "local_time": self.local_time,
            "local_time_iso": self.local_time_iso,
            "duration": self.duration,
            "remaining": self.remaining,
            "status": self.status.name.lower(),
            "label": self.label,
        }


class GoogleHomeAlarm:
    """Local representation of Google Home alarm."""

    def __init__(
        self,
        alarm_id: str,
        fire_time: int,
        status: int,
        label: str | None,
        recurrence: str | None,
    ) -> None:
        """Create Google Home Alarm object."""
        self.alarm_id = alarm_id
        self.recurrence = recurrence
        self.fire_time = convert_from_ms_to_s(fire_time)
        self.status = GoogleHomeAlarmStatus(status)
        self.label = label

        dt_utc = utc_from_timestamp(self.fire_time)
        dt_local = as_local(dt_utc)
        self.local_time = dt_local.strftime(DATETIME_STR_FORMAT)
        self.local_time_iso = dt_local.isoformat()

    def as_dict(self) -> GoogleHomeAlarmDict:
        """Return typed dict representation."""
        return {
            "alarm_id": self.alarm_id,
            "fire_time": self.fire_time,
            "local_time": self.local_time,
            "local_time_iso": self.local_time_iso,
            "status": self.status.name.lower(),
            "label": self.label,
            "recurrence": self.recurrence,
        }


class GoogleHomeAlarmStatus(Enum):
    """Definition of Google Home alarm status."""

    NONE = 0
    SET = 1
    RINGING = 2
    SNOOZED = 3
    INACTIVE = 4
    MISSED = 5


class GoogleHomeTimerStatus(Enum):
    """Definition of Google Home timer status."""

    NONE = 0
    SET = 1
    PAUSED = 2
    RINGING = 3
