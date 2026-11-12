"""Observed item events through real HA entities and invented speaker replies."""

from collections.abc import Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_mock_service

from custom_components.google_home.const import DOMAIN
from custom_components.google_home.event import AlarmEvents
from custom_components.google_home.models import GoogleHomeDevice

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.setup import async_setup_component

from .conftest import DELETE, INVALID_JSON, SPEAKER_ID, UNEXPECTED, Held, Replies
from .test_coordinators import runtime
from .test_entity import add_entity
from .test_fire_times import FIRE, alarm, timer
from .test_missing_devices import ALARM_ID, TIMER_ID
from .test_setup import set_up
from .test_unsupported_devices import (
    ALARMS,
    BUILD,
    DND,
    SPEAKER,
    SUPPORTED,
    VOLUME,
    Reply,
)

# pylint: enable=wrong-import-order

ALARM_EVENTS = "event.kitchen_speaker_alarm_events"
TIMER_EVENTS = "event.kitchen_speaker_timer_events"
OTHER_ID = "alarm/" + "f" * 36

pytestmark = pytest.mark.usefixtures("google")


def items(
    alarm_status: int | None = 1,
    timer_status: int | None = 1,
    *,
    alarm_id: str = ALARM_ID,
    label: object = "Wake up",
    at: int = 0,
    recurrence: object = None,
    duration: int = 60000,
) -> Reply:
    """Return complete, invented lists with distinct labels and occurrence times."""
    return HTTPStatus.OK, {
        "alarm": (
            [
                {
                    **alarm(alarm_status, at, alarm_id),
                    "label": label,
                    "recurrence": recurrence,
                }
            ]
            if alarm_status is not None
            else []
        ),
        "timer": (
            [{**timer(timer_status, 60), "label": "Tea", "original_duration": duration}]
            if timer_status is not None
            else []
        ),
    }


@pytest.fixture(name="received")
def fixture_received(hass: HomeAssistant) -> Iterator[list[State]]:
    """Capture every distinct event state, including simultaneous same-type items."""
    received: list[State] = []

    @callback
    def record(event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            new is not None
            and new.state not in {"unknown", "unavailable"}
            and (old is None or old.state != new.state)
        ):
            received.append(new)

    remove = async_track_state_change_event(hass, [ALARM_EVENTS, TIMER_EVENTS], record)
    yield received
    remove()


async def poll(
    hass: HomeAssistant, entry: MockConfigEntry, replies: Replies, reply: Reply
) -> None:
    """Finish one explicit serialized poll and deliver its listener updates."""
    replies[SPEAKER][ALARMS] = reply
    await runtime(entry).devices[SPEAKER_ID].async_refresh()
    await hass.async_block_till_done()


def changes(
    received: list[State],
) -> list[tuple[str, str, str, str | None, int | None]]:
    """Keep each event's own type, ID, label and occurrence time."""
    return [
        (
            state.entity_id,
            state.attributes["event_type"],
            state.attributes["item_id"],
            state.attributes["label"],
            state.attributes["fire_time"],
        )
        for state in received
    ]


async def test_ringing_repeat_and_removal(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A complete empty response ends each ringing ID and retains its metadata."""
    freezer.move_to(datetime(2026, 11, 1, 8, tzinfo=UTC))
    replies[SPEAKER][ALARMS] = items()
    await set_up(hass, config_entry)
    assert received == []
    await poll(hass, config_entry, replies, items(2, 3))
    await poll(hass, config_entry, replies, items(2, 3))
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    await poll(hass, config_entry, replies, items(None, None))
    assert changes(received) == [
        (ALARM_EVENTS, "ringing", ALARM_ID, "Wake up", FIRE),
        (TIMER_EVENTS, "ringing", TIMER_ID, "Tea", FIRE + 60),
        (ALARM_EVENTS, "stopped", ALARM_ID, "Wake up", FIRE),
        (TIMER_EVENTS, "stopped", TIMER_ID, "Tea", FIRE + 60),
    ]
    assert received[0].attributes["observed_at"] == "2026-11-01T08:00:00+00:00"
    assert received[0].attributes["previous_status"] == "set"
    assert received[-1].attributes["status"] == "removed"
    assert received[-1].attributes["previous_status"] == "ringing"
    # The removed timer's one-minute original_duration of 60000 ms
    assert received[-1].attributes["duration"] == "0:01:00"
    assert received[0].state < received[2].state


@pytest.mark.parametrize("turnover", [False, True])
async def test_snoozing_by_reported_id(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    turnover: bool,
) -> None:
    """Same-ID snooze emits one event; changed IDs also end the old ringing ID."""
    replies[SPEAKER][ALARMS] = items(2, None)
    await set_up(hass, config_entry)
    assert received == []  # Ringing at startup is a silent baseline.
    next_id = OTHER_ID if turnover else ALARM_ID
    await poll(
        hass,
        config_entry,
        replies,
        items(3, None, alarm_id=next_id, label="Later", at=600),
    )
    expected = [(ALARM_EVENTS, "snoozed", next_id, "Later", FIRE + 600)]
    if turnover:
        expected.insert(0, (ALARM_EVENTS, "stopped", ALARM_ID, "Wake up", FIRE))
    assert changes(received) == expected
    await poll(hass, config_entry, replies, items(None, None))
    assert changes(received) == expected  # No unseen post-snooze ring is inferred.


async def test_reset_and_observed_post_snooze_ring(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
) -> None:
    """Reset preserves the old ringing occurrence; a later observed ring is new."""
    replies[SPEAKER][ALARMS] = items(2, 3)
    await set_up(hass, config_entry)
    await poll(hass, config_entry, replies, items(1, 1, at=86400))
    assert changes(received) == [
        (ALARM_EVENTS, "stopped", ALARM_ID, "Wake up", FIRE),
        (TIMER_EVENTS, "stopped", TIMER_ID, "Tea", FIRE + 60),
    ]
    await poll(hass, config_entry, replies, items(3, None, at=87000))
    await poll(hass, config_entry, replies, items(2, None, at=87000))
    assert changes(received)[-2:] == [
        (ALARM_EVENTS, "snoozed", ALARM_ID, "Wake up", FIRE + 87000),
        (ALARM_EVENTS, "ringing", ALARM_ID, "Wake up", FIRE + 87000),
    ]


async def test_duration_and_recurrence_follow_the_ringing_item(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
) -> None:
    """Each kind gets only its own field, and stopped keeps the last ringing values."""
    replies[SPEAKER][ALARMS] = items(recurrence=[1, 2, 3, 4, 5], duration=600000)
    await set_up(hass, config_entry)
    await poll(
        hass,
        config_entry,
        replies,
        items(2, 3, recurrence=[1, 2, 3, 4, 5], duration=600000),
    )
    # Only these fields change while both keep ringing, which is no new event
    await poll(
        hass, config_entry, replies, items(2, 3, recurrence=[0, 6], duration=900000)
    )
    await poll(
        hass,
        config_entry,
        replies,
        items(1, 1, recurrence=[1], duration=300000, at=86400),
    )
    assert [
        (state.attributes["event_type"], state.attributes["recurrence"])
        for state in received
        if state.entity_id == ALARM_EVENTS
    ] == [("ringing", [1, 2, 3, 4, 5]), ("stopped", [0, 6])]
    # 600000 and 900000 ms are 10 and 15 minutes
    assert [
        (state.attributes["event_type"], state.attributes["duration"])
        for state in received
        if state.entity_id == TIMER_EVENTS
    ] == [("ringing", "0:10:00"), ("stopped", "0:15:00")]
    assert all(
        ("duration" in state.attributes) == (state.entity_id == TIMER_EVENTS)
        and ("recurrence" in state.attributes) == (state.entity_id == ALARM_EVENTS)
        for state in received
    )


@pytest.mark.parametrize(
    ("recurrence", "expected"),
    [
        ([0, 6], [0, 6]),
        ([], []),
        (None, None),
        ({"days": [1]}, None),
        ("1,2", None),
        ([1, "2"], None),
        ([True], None),
    ],
    ids=["weekend", "empty", "null", "object", "text", "mixed", "boolean"],
)
async def test_recurrence_is_whole_numbers_or_null(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    recurrence: object,
    expected: list[int] | None,
) -> None:
    """Only a list of whole numbers is passed on, as sent; anything else is null."""
    replies[SPEAKER][ALARMS] = items(timer_status=None)
    await set_up(hass, config_entry)
    await poll(hass, config_entry, replies, items(2, None, recurrence=recurrence))
    assert [state.attributes["recurrence"] for state in received] == [expected]


async def test_simultaneous_items_reach_event_received_automation(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    freezer: FrozenDateTimeFactory,
    tmp_path: Path,
) -> None:
    """Each frozen-clock event reaches real HA trigger handling with its own data."""
    freezer.move_to(datetime(2026, 11, 1, 8, tzinfo=UTC))
    replies[SPEAKER][ALARMS] = items(None, None)
    await set_up(hass, config_entry)
    hass.config.config_dir = str(tmp_path)
    calls = async_mock_service(hass, "test", "received")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "Every observed item",
                    "mode": "parallel",
                    "triggers": [
                        {
                            "trigger": "event.received",
                            "target": {"entity_id": [ALARM_EVENTS, TIMER_EVENTS]},
                            "options": {"event_type": ["ringing"]},
                        }
                    ],
                    "actions": [
                        {
                            "action": "test.received",
                            "data": {
                                "item_id": "{{ trigger.to_state.attributes.item_id }}",
                                "label": "{{ trigger.to_state.attributes.label }}",
                                "fire_time": "{{ trigger.to_state.attributes.fire_time }}",
                            },
                        }
                    ],
                }
            ]
        },
    )
    await poll(
        hass,
        config_entry,
        replies,
        (
            HTTPStatus.OK,
            {
                "alarm": [
                    {**alarm(2), "label": "Wake up", "recurrence": [1, 2, 3, 4, 5]},
                    {**alarm(2, 600, OTHER_ID), "label": "Later", "recurrence": [0, 6]},
                ],
                "timer": [{**timer(3, 60), "label": "Tea"}],
            },
        ),
    )
    assert changes(received) == [
        (ALARM_EVENTS, "ringing", ALARM_ID, "Wake up", FIRE),
        (ALARM_EVENTS, "ringing", OTHER_ID, "Later", FIRE + 600),
        (TIMER_EVENTS, "ringing", TIMER_ID, "Tea", FIRE + 60),
    ]
    assert [
        received[0].attributes["recurrence"],
        received[1].attributes["recurrence"],
        received[2].attributes["duration"],
    ] == [[1, 2, 3, 4, 5], [0, 6], "0:01:00"]
    assert [dict(call.data) for call in calls] == [
        {"item_id": ALARM_ID, "label": "Wake up", "fire_time": FIRE},
        {"item_id": OTHER_ID, "label": "Later", "fire_time": FIRE + 600},
        {"item_id": TIMER_ID, "label": "Tea", "fire_time": FIRE + 60},
    ]
    assert received[0].state < received[1].state


@pytest.mark.parametrize("endpoint", [DND, BUILD])
async def test_action_cannot_replace_pending_poll(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    endpoint: str,
) -> None:
    """An action can replace/delete live items while poll-owned event data survives."""
    replies[SPEAKER][ALARMS] = items()
    await set_up(hass, config_entry)
    device = runtime(config_entry).devices[SPEAKER_ID].data
    assert device is not None
    device.firmware_checked_at = None
    held = Held(SUPPORTED[endpoint])
    replies[SPEAKER][endpoint] = held
    replies[SPEAKER][ALARMS] = items(2, 3, recurrence=[1, 2, 3, 4, 5], duration=600000)
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    refresh = hass.async_create_task(coordinator.async_refresh())
    await held.asked.wait()
    replies[SPEAKER][ALARMS] = items(
        1, None, label="Action replacement", at=3600, recurrence=[0]
    )
    replies[SPEAKER][DELETE] = HTTPStatus.OK, {"success": True}
    await hass.services.async_call(
        DOMAIN,
        "delete_alarm",
        {
            "entity_id": "sensor.kitchen_speaker_alarms",
            "alarm_id": ALARM_ID,
            "skip_refresh": True,
        },
        blocking=True,
    )
    assert received == []
    held.released.set()
    await refresh
    await hass.async_block_till_done()
    assert changes(received) == [
        (ALARM_EVENTS, "ringing", ALARM_ID, "Wake up", FIRE),
        (TIMER_EVENTS, "ringing", TIMER_ID, "Tea", FIRE + 60),
    ]
    # The poll's values, not the action's replacement or the timer it no longer has
    assert received[0].attributes["recurrence"] == [1, 2, 3, 4, 5]
    assert received[1].attributes["duration"] == "0:10:00"
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert len(received) == 2


@pytest.mark.parametrize(
    ("endpoint", "failure"),
    [
        (ALARMS, TimeoutError()),
        (ALARMS, HTTPStatus.INTERNAL_SERVER_ERROR),
        (ALARMS, (HTTPStatus.OK, INVALID_JSON)),
        (ALARMS, (HTTPStatus.OK, {"alarm": []})),
        (ALARMS, (HTTPStatus.OK, {"timer": []})),
        (ALARMS, (HTTPStatus.OK, {"alarm": [{"id": ALARM_ID}], "timer": []})),
        (DND, TimeoutError()),
        (VOLUME, UNEXPECTED),
    ],
)
async def test_failure_breaks_continuity(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    endpoint: str,
    failure: Reply,
) -> None:
    """Neither a failed poll nor its recovery baseline fabricates a transition."""
    replies[SPEAKER][ALARMS] = items(2, 3)
    await set_up(hass, config_entry)
    replies[SPEAKER][endpoint] = failure
    if endpoint == ALARMS:
        coordinator = runtime(config_entry).devices[SPEAKER_ID]
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    else:
        await poll(hass, config_entry, replies, items(None, None))
    replies[SPEAKER][endpoint] = SUPPORTED[endpoint]
    await poll(hass, config_entry, replies, items(None, None))
    assert received == []
    await poll(hass, config_entry, replies, items(2, 3))
    assert [s.attributes["event_type"] for s in received] == ["ringing", "ringing"]


@pytest.mark.parametrize(
    "lifecycle", ["unlist-relist", "replacement", "shutdown", "disabled", "unsupported"]
)
async def test_lifecycle_during_pending_poll(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
    lifecycle: str,
) -> None:
    """A held poll cannot commit across lifecycle invalidation, including same-object ABA."""
    replies[SPEAKER][ALARMS] = items()
    await set_up(hass, config_entry)
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    device = coordinator.data
    assert device is not None
    held = Held(SUPPORTED[DND])
    replies[SPEAKER][DND] = held
    replies[SPEAKER][ALARMS] = items(2, 3)
    refresh = hass.async_create_task(coordinator.async_refresh())
    await held.asked.wait()
    if lifecycle == "unlist-relist":
        coordinator.client.google_devices.clear()
        coordinator.async_unlisted()
        coordinator.client.google_devices.append(device)
    elif lifecycle == "replacement":
        coordinator.client.google_devices[:] = [
            GoogleHomeDevice(SPEAKER_ID, "Replacement", "token", SPEAKER)
        ]
    elif lifecycle == "shutdown":
        await coordinator.async_shutdown()
    elif lifecycle == "disabled":
        registry = dr.async_get(hass)
        entry = registry.async_get_device_by_identifier(
            (DOMAIN, SPEAKER_ID), config_entry.entry_id
        )
        assert entry is not None
        registry.async_update_device(entry.id, disabled_by=dr.DeviceEntryDisabler.USER)
    else:
        device.alarms_unsupported = True
    held.released.set()
    await refresh
    await hass.async_block_till_done()
    assert received == []
    if lifecycle in {"unlist-relist", "replacement"}:
        await poll(hass, config_entry, replies, items(None, None))
        assert received == []


async def test_unknown_duplicates_and_metadata_only_changes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
) -> None:
    """Unknown status and ambiguous IDs cannot prove an end; metadata is primitive."""
    replies[SPEAKER][ALARMS] = items(2, 3)
    await set_up(hass, config_entry)
    await poll(
        hass, config_entry, replies, items(2, 3, label={"unexpected": "mutable"}, at=99)
    )
    assert received == []
    await poll(hass, config_entry, replies, items(999, 999))
    await poll(hass, config_entry, replies, items(None, None))
    assert received == []
    await poll(
        hass,
        config_entry,
        replies,
        (HTTPStatus.OK, {"alarm": [alarm(2), alarm(2)], "timer": []}),
    )
    await poll(hass, config_entry, replies, items(2, 3))
    assert received == []
    await poll(hass, config_entry, replies, items(None, None))
    assert len(received) == 2


async def test_registry_and_reload_baseline(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    entity_registry: er.EntityRegistry,
    tmp_path: Path,
) -> None:
    """Events have stable registry IDs and a reload does not interpret initial lists."""
    replies[SPEAKER][ALARMS] = items()
    await set_up(hass, config_entry)
    for entity_id, suffix, types in (
        (ALARM_EVENTS, "alarm_events", ["ringing", "snoozed", "stopped"]),
        (TIMER_EVENTS, "timer_events", ["ringing", "stopped"]),
    ):
        entity = entity_registry.async_get(entity_id)
        state = hass.states.get(entity_id)
        assert entity is not None and state is not None
        assert entity.unique_id == f"{SPEAKER_ID}/{suffix}"
        assert entity.entity_category is None
        assert state.state == "unknown"
        assert state.attributes["event_types"] == types
    hass.config.config_dir = str(tmp_path)
    calls = async_mock_service(hass, "test", "received")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "Ignore restored event history",
                    "mode": "parallel",
                    "triggers": [
                        {
                            "trigger": "event.received",
                            "target": {"entity_id": [ALARM_EVENTS, TIMER_EVENTS]},
                            "options": {
                                "event_type": ["ringing", "snoozed", "stopped"]
                            },
                        }
                    ],
                    "actions": [{"action": "test.received"}],
                }
            ]
        },
    )
    await poll(hass, config_entry, replies, items(2, 3))
    last_event = hass.states.get(ALARM_EVENTS)
    assert last_event is not None
    assert len(calls) == 2
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, config_entry, replies, items(2, 3))
    assert runtime(config_entry).devices[SPEAKER_ID].events == ()
    restored = hass.states.get(ALARM_EVENTS)
    assert restored is not None and restored.state == last_event.state
    assert restored.attributes["item_id"] == ALARM_ID
    assert len(calls) == 2


async def test_successful_action_during_failed_poll(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
) -> None:
    """An action's valid ringing reply cannot rescue a failed polling observation."""
    replies[SPEAKER][ALARMS] = items()
    await set_up(hass, config_entry)
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    held = Held(TimeoutError())
    replies[SPEAKER][ALARMS] = held
    refresh = hass.async_create_task(coordinator.async_refresh())
    await held.asked.wait()
    replies[SPEAKER][ALARMS] = (
        HTTPStatus.OK,
        {
            "alarm": [alarm(2), alarm(1, 600, OTHER_ID)],
            "timer": [],
        },
    )
    replies[SPEAKER][DELETE] = HTTPStatus.OK, {"success": True}
    await hass.services.async_call(
        DOMAIN,
        "delete_alarm",
        {
            "entity_id": "sensor.kitchen_speaker_alarms",
            "alarm_id": OTHER_ID,
            "skip_refresh": True,
        },
        blocking=True,
    )
    held.released.set()
    await refresh
    await hass.async_block_till_done()
    assert received == []
    await poll(hass, config_entry, replies, items(2, 3))
    assert received == []
    await poll(hass, config_entry, replies, items(None, None))
    assert [state.attributes["event_type"] for state in received] == [
        "stopped",
        "stopped",
    ]


async def test_primitive_metadata_and_timer_without_time(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
) -> None:
    """Malformed labels and missing timer times never leak mutable or invented data."""
    replies[SPEAKER][ALARMS] = items(None, None)
    await set_up(hass, config_entry)
    await poll(
        hass,
        config_entry,
        replies,
        (
            HTTPStatus.OK,
            {
                "alarm": [{**alarm(2), "label": {"mutable": "label"}}],
                "timer": [timer(3, None)],
            },
        ),
    )
    assert changes(received) == [
        (ALARM_EVENTS, "ringing", ALARM_ID, None, FIRE),
        (TIMER_EVENTS, "ringing", TIMER_ID, None, None),
    ]
    # The alarm has no recurrence key
    assert received[0].attributes["recurrence"] is None


async def test_new_entity_does_not_replay_published_batch(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    received: list[State],
) -> None:
    """Adding a listener after publication consumes history without triggering it."""
    replies[SPEAKER][ALARMS] = items()
    await set_up(hass, config_entry)
    await poll(hass, config_entry, replies, items(2, None))
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    new = AlarmEvents(
        coordinator, coordinator.client, SPEAKER_ID, "Kitchen speaker", None
    )
    # A separate registry identity models a newly enabled listener without replacing
    # the existing entity or altering the coordinator's observation baseline.
    new.device_id = "new-listener"
    entity_id = await add_entity(hass, config_entry, "event", new)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None and state.state == "unknown"
    assert len(received) == 1
