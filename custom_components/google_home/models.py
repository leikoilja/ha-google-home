"""Models for Google Home."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import Enum
from http import HTTPStatus
import logging
import math
import sys
from typing import Self, override

from homeassistant.util.dt import as_local, utc_from_timestamp

from .const import (
    DATETIME_STR_FORMAT,
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    JSON_ALARM,
    JSON_TIMER,
    UNANSWERED_UPDATES,
)
from .observations import PollObservation
from .types import (
    AlarmJsonDict,
    GoogleHomeAlarmDict,
    GoogleHomeTimerDict,
    JsonDict,
    TimerJsonDict,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def convert_from_ms_to_s(timestamp: int) -> int:
    """Convert from milliseconds to seconds."""
    return round(timestamp / 1000)


def is_number(value: object) -> bool:
    """Return whether a JSON value is a whole number or a finite one.

    True and false aren't numbers. A whole number isn't turned into a float to check
    it, so one too large to convert is left for its conversion to reject.
    """
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, int) and not isinstance(value, bool)


def is_item(
    item: object, numbers: tuple[str, ...], optional_numbers: tuple[str, ...] = ()
) -> bool:
    """Return whether an alarm or timer has its ID, its status and these numbers.

    The status must be a whole number, and an optional number may be missing or null.
    """
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(status := item.get("status"), int)
        and not isinstance(status, bool)
        and all(is_number(item.get(key)) for key in numbers)
        and all(
            item.get(key) is None or is_number(item[key]) for key in optional_numbers
        )
    )


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
        home_name: str | None = None,
    ):
        """Create Google Home device object."""
        self.device_id = device_id
        self.name = name
        self.auth_token = auth_token
        self.ip_address = ip_address
        self.hardware = hardware
        # Google's ID for the device, which it also reports locally
        self.cloud_device_id = cloud_device_id.lower() if cloud_device_id else None
        # The name of its home in the Google Home app, if Google gives one
        self.home_name = home_name
        # Whether the last request for alarms, settings or a reboot was answered 200,
        # even with a reply that isn't valid JSON or isn't in the expected form. Its
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
        # Updates that couldn't ask the device, as it had no address. Its alarms,
        # timers and settings entities read them only while it still has none.
        self.addressless_updates = 0
        # The failures of its updates' requests that were logged as errors, by type,
        # until an update works, and whether a request of the running update failed
        self.logged_failures: set[str] = set()
        self.update_failed = False
        self.do_not_disturb = False
        self.alarm_volume = GOOGLE_HOME_ALARM_DEFAULT_VALUE
        self._timers: list[GoogleHomeTimer] = []
        self._alarms: list[GoogleHomeAlarm] = []
        # The last answer to a request for its alarms and timers, as it came, for
        # diagnostics
        self.alarms_reply: JsonDict | None = None
        # Updates whose request for alarms and timers got both lists. Actions' requests
        # don't count, so an update can tell whether it got the lists itself.
        self.polled_snapshots = 0
        # Only a successful poll assigns this immutable projection; actions never do.
        self.poll_observation: PollObservation | None = None
        # The firmware fields of its last build info, as it sent them
        self.build_info: dict[str, object] | None = None
        # Whether its info said at the last check that a firmware update is waiting,
        # or None if it didn't say
        self.has_update: bool | None = None
        # The Wi-Fi network and signal strength in dBm that its info gave at the last
        # check, or None if it didn't give them. A Nest Hub gives no signal.
        self.wifi_ssid: str | None = None
        self.wifi_signal: float | None = None
        # Estimated last boot from the latest info reply, before HA suppresses drift
        self.booted_at: datetime | None = None
        # When the last check of its firmware started
        self.firmware_checked_at: float | None = None

    @property
    def sw_version(self) -> str | None:
        """Return the firmware version in the form Google publishes for the device.

        A display reports its system version, such as 31.20260101.103.1234567, as its
        system build number. A speaker or Chromecast Audio reports only a build there,
        the last part of its Cast version, such as 3.77.512345, which is the one
        Google publishes for it.
        """
        info = self.build_info or {}
        system = info.get("system_build_number")
        cast = info.get("cast_build_revision")
        if isinstance(system, str) and "." in system:
            return system
        if isinstance(cast, str) and cast:
            return cast
        return system if isinstance(system, str) and system else None

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

    def set_alarms_and_timers(self, reply: Mapping[str, object]) -> bool:
        """Store the alarms and timers of a reply to the alarms request, if it can be read.

        Return whether it could. Otherwise keep the ones the device has, so the reply
        doesn't leave new timers next to old alarms: it needs a list of each, whose
        items all have the fields that GoogleHomeAlarm and GoogleHomeTimer read, with
        times that can be converted. Their labels and recurrences are kept as they come.
        """
        alarms, timers = reply.get(JSON_ALARM), reply.get(JSON_TIMER)
        if not (
            isinstance(alarms, list)
            and isinstance(timers, list)
            and all(is_item(alarm, ("fire_time",)) for alarm in alarms)
            and all(
                is_item(
                    timer, ("original_duration",), ("fire_time", "remaining_duration")
                )
                for timer in timers
            )
        ):
            return False
        try:
            new_alarms = [GoogleHomeAlarm.from_json(alarm) for alarm in alarms]
            new_timers = [GoogleHomeTimer.from_json(timer) for timer in timers]
        # A time too far off to convert, such as a year after 9999
        except ValueError, OverflowError, OSError:
            return False
        self._alarms, self._timers = new_alarms, new_timers
        return True

    def set_alarms(self, alarms: list[AlarmJsonDict]) -> None:
        """Store alarms as GoogleHomeAlarm objects."""
        self._alarms = [GoogleHomeAlarm.from_json(alarm) for alarm in alarms]

    def set_timers(self, timers: list[TimerJsonDict]) -> None:
        """Store timers as GoogleHomeTimer objects."""
        self._timers = [GoogleHomeTimer.from_json(timer) for timer in timers]

    def remove_alarms_and_timers(self, ids: list[str]) -> None:
        """Remove the alarms and timers with these IDs."""
        self._alarms = [alarm for alarm in self._alarms if alarm.alarm_id not in ids]
        self._timers = [timer for timer in self._timers if timer.timer_id not in ids]

    def get_sorted_alarms(self) -> list[GoogleHomeAlarm]:
        """Return alarms in a sorted order. Inactive, missed and unknown alarms are at the end."""
        return sorted(
            self._alarms,
            key=lambda k: (
                k.fire_time
                if k.status not in LAST_ALARM_STATUSES
                else k.fire_time + sys.maxsize
            ),
        )

    def get_next_alarm(self) -> GoogleHomeAlarm | None:
        """Return next alarm."""
        alarms = self.get_sorted_alarms()
        return alarms[0] if alarms else None

    def get_sorted_timers(self) -> list[GoogleHomeTimer]:
        """Return timers in a sorted order. Paused timers and unknown statuses are at the end."""
        return sorted(
            self._timers,
            key=lambda k: (
                k.fire_time
                if k.fire_time is not None
                and k.status is not GoogleHomeTimerStatus.UNKNOWN
                else sys.maxsize
            ),
        )

    def get_next_timer(self) -> GoogleHomeTimer | None:
        """Return next alarm."""
        timers = self.get_sorted_timers()
        return timers[0] if timers else None


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

    @classmethod
    def from_json(cls, timer: TimerJsonDict) -> Self:
        """Create a timer from its JSON, as the device sends it."""
        return cls(
            timer_id=timer["id"],
            fire_time=timer.get("fire_time"),
            duration=timer["original_duration"],
            remaining=timer.get("remaining_duration"),
            status=timer["status"],
            label=timer.get("label"),
        )

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

    @classmethod
    def from_json(cls, alarm: AlarmJsonDict) -> Self:
        """Create an alarm from its JSON, as the device sends it."""
        return cls(
            alarm_id=alarm["id"],
            fire_time=alarm["fire_time"],
            status=alarm["status"],
            label=alarm.get("label"),
            recurrence=alarm.get("recurrence"),
        )

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
    # A status the integration doesn't know, such as one that newer firmware adds
    UNKNOWN = -1

    @classmethod
    @override
    def _missing_(cls, value: object) -> Self:
        """Return UNKNOWN for a status the integration doesn't know."""
        return cls.UNKNOWN


class GoogleHomeTimerStatus(Enum):
    """Definition of Google Home timer status."""

    NONE = 0
    SET = 1
    PAUSED = 2
    RINGING = 3
    # A status the integration doesn't know, such as one that newer firmware adds
    UNKNOWN = -1

    @classmethod
    @override
    def _missing_(cls, value: object) -> Self:
        """Return UNKNOWN for a status the integration doesn't know."""
        return cls.UNKNOWN


# The statuses of the alarms that come last, and whose time the alarms sensor never
# shows
LAST_ALARM_STATUSES = frozenset(
    {
        GoogleHomeAlarmStatus.INACTIVE,
        GoogleHomeAlarmStatus.MISSED,
        GoogleHomeAlarmStatus.UNKNOWN,
    }
)
