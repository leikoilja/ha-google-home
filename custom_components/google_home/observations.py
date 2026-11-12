"""Immutable polling observations and transitions under each reported item ID."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .models import GoogleHomeDevice

type ItemKind = Literal["alarm", "timer"]


@dataclass(frozen=True)
class ItemObservation:
    """The primitive fields of one item in a successfully parsed poll."""

    item_id: str
    status: str
    label: str | None
    fire_time: int | None
    # A timer's length, as the timers sensor shows it
    duration: str | None = None
    # An alarm's repeat days, only if the speaker sent a list of whole numbers
    recurrence: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PollObservation:
    """Both complete lists, owned by a poll rather than by subsequent actions."""

    sequence: int
    observed_at: str
    alarms: tuple[ItemObservation, ...]
    timers: tuple[ItemObservation, ...]


@dataclass(frozen=True)
class ItemEvent:
    """An observed change, whose metadata cannot be overwritten by another item."""

    kind: ItemKind
    event_type: str
    item: ItemObservation
    observed_at: str
    previous_status: str | None
    status: str

    def attributes(self) -> dict[str, str | int | list[int] | None]:
        """Return a fresh event payload of primitives and a new list of repeat days."""
        attributes: dict[str, str | int | list[int] | None] = {
            "item_id": self.item.item_id,
            "label": self.item.label,
            "fire_time": self.item.fire_time,
            "observed_at": self.observed_at,
            "previous_status": self.previous_status,
            "status": self.status,
        }
        if self.kind == "alarm":
            recurrence = self.item.recurrence
            attributes["recurrence"] = None if recurrence is None else list(recurrence)
        else:
            attributes["duration"] = self.item.duration
        return attributes


def _weekdays(recurrence: object) -> tuple[int, ...] | None:
    """Return an alarm's repeat days if they are a list of whole numbers, else None."""
    if isinstance(recurrence, list) and all(
        isinstance(day, int) and not isinstance(day, bool) for day in recurrence
    ):
        return tuple(recurrence)
    return None


def observe_poll(device: GoogleHomeDevice) -> PollObservation | None:
    """Copy a parsed poll before yielding, rejecting ambiguous duplicate IDs."""
    alarms = tuple(
        ItemObservation(
            alarm.alarm_id,
            alarm.status.name.lower(),
            alarm.label if isinstance(alarm.label, str) else None,
            alarm.fire_time,
            recurrence=_weekdays(alarm.recurrence),
        )
        for alarm in device.get_sorted_alarms()
    )
    timers = tuple(
        ItemObservation(
            timer.timer_id,
            timer.status.name.lower(),
            timer.label if isinstance(timer.label, str) else None,
            timer.fire_time,
            duration=timer.duration,
        )
        for timer in device.get_sorted_timers()
    )
    if len({item.item_id for item in alarms}) != len(alarms) or len(
        {item.item_id for item in timers}
    ) != len(timers):
        return None
    return PollObservation(
        device.polled_snapshots, dt_util.utcnow().isoformat(), alarms, timers
    )


def observed_events(
    previous: PollObservation, current: PollObservation
) -> tuple[ItemEvent, ...]:
    """Compare reported IDs without inferring physical identity across different IDs."""
    events: list[ItemEvent] = []
    kinds: tuple[ItemKind, ...] = ("alarm", "timer")
    for kind in kinds:
        old_items = previous.alarms if kind == "alarm" else previous.timers
        new_items = current.alarms if kind == "alarm" else current.timers
        old = {item.item_id: item for item in old_items}
        new = {item.item_id: item for item in new_items}
        for item_id in sorted(old.keys() | new.keys()):
            before, after = old.get(item_id), new.get(item_id)
            before_status = before.status if before else None
            after_status = after.status if after else "removed"
            if "unknown" in {before_status, after_status}:
                continue
            if after_status == before_status:
                continue
            if after and (
                after_status == "ringing"
                or (kind == "alarm" and after_status == "snoozed")
            ):
                event_type, item = after_status, after
            elif before and before_status == "ringing":
                event_type, item = "stopped", before
            else:
                continue
            events.append(
                ItemEvent(
                    kind,
                    event_type,
                    item,
                    current.observed_at,
                    before_status,
                    after_status,
                )
            )
    return tuple(events)
