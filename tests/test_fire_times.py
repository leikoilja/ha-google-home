"""Tests for asking a speaker around its alarms' and timers' fire times.

As in test_setup, the integration runs inside Home Assistant, and only glocaltokens,
mDNS and the speakers' answers are faked. The clock moves a second at a time. Home
Assistant starts each update a fixed fraction of a second after a whole second, which
the tests set to 0.5 s, the most it uses, so with a clock that starts on a whole second
every request is sent at a whole second.

The times are in seconds after the alarm's or timer's fire time. The speaker answers
the alarms request with the reply of the latest change at or before that second.
"""

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from time import time
from unittest.mock import Mock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import (
    API_ENDPOINT_ALARMS,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import event

from .conftest import (
    BEDROOM,
    DELETE,
    SPEAKER_ID,
    Held,
    Replies,
    bedroom_speaker,
    kitchen_speaker,
)
from .test_coordinators import runtime
from .test_missing_devices import ALARM_ID, TIMER_ID
from .test_setup import set_up, state
from .test_unsupported_devices import ALARMS, DND, SPEAKER, SUPPORTED, VOLUME, Reply

# pylint: enable=wrong-import-order

# The fire time of the alarms and timers, unless a test gives another
FIRE = int(datetime(2026, 11, 1, 8, 0, tzinfo=UTC).timestamp())
ALARMS_SENSOR = "sensor.kitchen_speaker_alarms"
TIMERS_SENSOR = "sensor.kitchen_speaker_timers"
# The statuses in the speaker's answers
ALARM_SET, ALARM_RINGING, ALARM_SNOOZED, ALARM_INACTIVE, ALARM_MISSED = 1, 2, 3, 4, 5
TIMER_SET, TIMER_PAUSED, TIMER_RINGING = 1, 2, 3
# The default update interval of older installs, longer than the ringing interval
INTERVAL = 180
OTHER_ALARM_ID = "alarm/" + "1" * 36
MISSED_ALARM_ID = "alarm/" + "2" * 36
PAUSED_TIMER_ID = "timer/" + "1" * 36


def alarm(status: int, at: float = 0, alarm_id: str = ALARM_ID) -> dict[str, int | str]:
    """Return an alarm as the speaker answers, due this many seconds after FIRE."""
    return {"id": alarm_id, "fire_time": int((FIRE + at) * 1000), "status": status}


def timer(
    status: int, at: float | None = 0, timer_id: str = TIMER_ID
) -> dict[str, int | str]:
    """Return a one-minute timer as the speaker answers, due this many seconds after FIRE.

    A paused timer, or one without a fire time, has None.
    """
    item: dict[str, int | str] = {
        "id": timer_id,
        "original_duration": 60000,
        "status": status,
    }
    if at is not None:
        item["fire_time"] = int((FIRE + at) * 1000)
    return item


def answer(
    *alarms: dict[str, int | str], timers: tuple[dict[str, int | str], ...] = ()
) -> Reply:
    """Return the speaker's answer to the alarms request, with these alarms and timers."""
    return HTTPStatus.OK, {"alarm": list(alarms), "timer": list(timers)}


SET = answer(alarm(ALARM_SET))
RINGING = answer(alarm(ALARM_RINGING))
NONE_LEFT = answer()


def seconds() -> float:
    """Return the time, in seconds after FIRE."""
    return round(time() - FIRE, 1)


def next_alarm_status(hass: HomeAssistant) -> str:
    """Return the status of the next alarm that the alarms sensor shows."""
    entity_state = hass.states.get(ALARMS_SENSOR)
    assert entity_state is not None
    status: str = entity_state.attributes["next_alarm_status"]
    return status


@pytest.fixture(autouse=True)
def fixture_update_fraction() -> Iterator[None]:
    """Start each coordinator's updates 0.5 s after a whole second."""
    with patch(
        "homeassistant.helpers.update_coordinator.randint",
        return_value=event.RANDOM_MICROSECOND_MAX,
    ):
        yield


@pytest.fixture(name="window")
def fixture_window() -> Iterator[None]:
    """Shorten the ringing window to 2 minutes, so a test sees it end."""
    with patch("custom_components.google_home.coordinator.RINGING_WINDOW", 120):
        yield


async def start(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    replies: Replies,
    freezer: FrozenDateTimeFactory,
    at: float,
    reply: Reply,
    interval: int = INTERVAL,
) -> None:
    """Set up the entry this many seconds after FIRE, with the speaker answering reply."""
    freezer.move_to(datetime.fromtimestamp(FIRE + at, UTC))
    hass.config_entries.async_update_entry(
        entry, options={CONF_UPDATE_INTERVAL: interval}
    )
    replies[SPEAKER][ALARMS] = reply
    await set_up(hass, entry)


def alarms_asked(aioclient_mock: AiohttpClientMocker) -> bool:
    """Return whether the speaker was asked for its alarms since the last call."""
    asked = any(
        method.upper() == "GET"
        and url.host == SPEAKER
        and url.path_qs.removeprefix("/") == API_ENDPOINT_ALARMS
        for method, url, _, _ in aioclient_mock.mock_calls
    )
    aioclient_mock.mock_calls.clear()
    return asked


async def run(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    replies: Replies,
    until: float,
    changes: Mapping[int, Reply] | None = None,
) -> list[float]:
    """Move the clock a second at a time, to this many seconds after FIRE.

    At each change's time, before the updates due then, the speaker starts answering
    the alarms request with its reply. Return when the speaker was asked for its alarms.
    """
    changes = changes or {}
    asked: list[float] = []
    alarms_asked(aioclient_mock)
    while seconds() < until:
        freezer.tick(timedelta(seconds=1))
        reply = changes.get(int(now)) if (now := seconds()).is_integer() else None
        if reply is not None:
            replies[SPEAKER][ALARMS] = reply
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
        if alarms_asked(aioclient_mock):
            asked.append(seconds())
    return asked


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("at", "asked"),
    [
        # 63 s before the next update at the interval
        pytest.param(-60, [3, 8, 13, 18, 23, 28, 33, 213], id="due-before-next-update"),
        # The next update, at -120, comes first
        pytest.param(
            -300, [-120, 3, 8, 13, 18, 23, 28, 33, 213], id="due-after-next-update"
        ),
        # The update at the interval comes 1 s after the fire time, so it's the first
        pytest.param(
            -179, [1, 6, 11, 16, 21, 26, 31, 211], id="update-after-fire-time"
        ),
        # The update for 3 s after the fire time comes 0.4 s early, as it can when it's
        # timed from a fraction of a second, and finds the alarm still set
        pytest.param(
            -59.4,
            [2.6, 7.6, 12.6, 17.6, 22.6, 27.6, 32.6, 212.6],
            id="update-early",
        ),
    ],
)
async def test_asked_after_fire_time_until_ringing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    at: float,
    asked: list[float],
) -> None:
    """Ask a speaker 3 s after its alarm's fire time, then every 5 s while it isn't ringing.

    Until an update at least 30 s after the fire time, then at the interval again. An
    update that comes before the one for 3 s after doesn't replace it, and the first
    one after the fire time starts the 5-second updates.
    """
    await start(hass, config_entry, replies, freezer, at, SET)

    assert await run(hass, aioclient_mock, freezer, replies, asked[-1]) == asked


@pytest.mark.usefixtures("google")
async def test_ringing_alarm_until_dismissed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask every 15 s while the alarm rings, and show its dismissal at the next update."""
    await start(hass, config_entry, replies, freezer, -60, SET)
    changes = {0: RINGING, 40: NONE_LEFT}

    assert await run(hass, aioclient_mock, freezer, replies, 3, changes) == [3]
    assert next_alarm_status(hass) == "ringing"
    assert await run(hass, aioclient_mock, freezer, replies, 47, changes) == [18, 33]
    assert next_alarm_status(hass) == "ringing"
    assert await run(hass, aioclient_mock, freezer, replies, 48 + INTERVAL) == [
        48,
        48 + INTERVAL,
    ]
    assert next_alarm_status(hass) == "none"


@pytest.mark.usefixtures("google", "window")
@pytest.mark.parametrize(
    ("changes", "asked", "status"),
    [
        # Dismissed after the last update every 15 s before the end of the window, and
        # shown by the update after the end
        pytest.param(
            {0: RINGING, 115: NONE_LEFT},
            [3, 18, 33, 48, 63, 78, 93, 108, 123, 303, 483],
            "none",
            id="dismissed-before-end",
        ),
        pytest.param(
            {0: RINGING},
            [3, 18, 33, 48, 63, 78, 93, 108, 123, 303, 483],
            "ringing",
            id="rings-on",
        ),
        # The speaker reports a later fire time at every update while it rings, which
        # doesn't move the end of the window
        pytest.param(
            {at: answer(alarm(ALARM_RINGING, at)) for at in range(484)},
            [3, 18, 33, 48, 63, 78, 93, 108, 123, 303, 483],
            "ringing",
            id="fire-time-moves",
        ),
    ],
)
async def test_ringing_window(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    changes: dict[int, Reply],
    asked: list[float],
    status: str,
) -> None:
    """Ask every 15 s while the alarm rings, until an update after the end of its window.

    Then at the interval while it still rings.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)

    assert await run(hass, aioclient_mock, freezer, replies, 483, changes) == asked
    assert next_alarm_status(hass) == status


async def hold_dnd(
    hass: HomeAssistant,
    replies: Replies,
    freezer: FrozenDateTimeFactory,
    seconds_held: int,
    then: Reply,
) -> None:
    """Run the update due in the next second, with its Do Not Disturb answer held this long.

    Once it has asked for the alarms, the speaker answers that request with then.
    """
    held = Held(SUPPORTED[DND])
    replies[SPEAKER][DND] = held
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    replies[SPEAKER][ALARMS] = then
    for _ in range(seconds_held):
        freezer.tick(timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    replies[SPEAKER][DND] = SUPPORTED[DND]
    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.usefixtures("google", "window")
@pytest.mark.parametrize(
    ("then", "status"),
    [(NONE_LEFT, "none"), (TimeoutError(), "ringing")],
    ids=["answered", "not-answered"],
)
async def test_ringing_window_ends_after_slow_update(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    then: Reply,
    status: str,
) -> None:
    """Ask again after an update that asked for the alarms before the end of the window.

    Also when that update finishes after it. The alarm rang until 28 s after its fire
    time, and is dismissed 1 s after the last update every 15 s asked for it. If the
    next update gets no answer, it shows nothing, and the next one is at the interval.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    changes = {28: RINGING}

    assert await run(hass, aioclient_mock, freezer, replies, 117, changes) == [
        3,
        8,
        13,
        18,
        23,
        28,
        43,
        58,
        73,
        88,
        103,
    ]
    # Asked at 118 s, while it still rang
    await hold_dnd(hass, replies, freezer, 4, then)
    assert alarms_asked(aioclient_mock)
    assert seconds() == 122
    assert await run(hass, aioclient_mock, freezer, replies, 137 + INTERVAL) == [
        137,
        137 + INTERVAL,
    ]
    assert next_alarm_status(hass) == status


@pytest.mark.usefixtures("google")
async def test_ringing_shown_after_slow_update_before_onset_end(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask again after an update that asked before 30 s after the fire time, and finished after.

    The alarm starts ringing after that update asked for it.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)

    assert await run(hass, aioclient_mock, freezer, replies, 27) == [3, 8, 13, 18, 23]
    # Asked at 28 s, while it was still set
    await hold_dnd(hass, replies, freezer, 4, RINGING)
    assert seconds() == 32
    assert await run(hass, aioclient_mock, freezer, replies, 52) == [37, 52]
    assert next_alarm_status(hass) == "ringing"


@pytest.mark.usefixtures("google")
async def test_ringing_shown_once_update_finishes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Show the ringing that an update got only once its other requests are answered."""
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 2, {0: RINGING}) == []
    held = Held(SUPPORTED[DND])
    replies[SPEAKER][DND] = held

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    await hass.async_block_till_done()
    assert alarms_asked(aioclient_mock)
    assert next_alarm_status(hass) == "set"

    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert next_alarm_status(hass) == "ringing"


@pytest.mark.usefixtures("google", "window")
@pytest.mark.parametrize(
    ("changes", "asked"),
    [
        # Snoozed until 600 s after the first fire time, after its 2-minute window,
        # then ringing again from 606 s: the first update after the new fire time
        # finds it still snoozed, so every 5 s until it rings
        pytest.param(
            {
                0: RINGING,
                20: answer(alarm(ALARM_SNOOZED, 600)),
                606: answer(alarm(ALARM_RINGING, 600)),
            },
            [3, 18, 33, 213, 393, 573, 603, 608, 623, 638],
            id="snoozed",
        ),
        # A recurring alarm, set again for its next time once it stops, here 600 s
        # after the first, after its 2-minute window
        pytest.param(
            {
                0: RINGING,
                20: answer(alarm(ALARM_SET, 600)),
                600: answer(alarm(ALARM_RINGING, 600)),
            },
            [3, 18, 33, 213, 393, 573, 603, 618, 633],
            id="recurring",
        ),
    ],
)
async def test_after_ringing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    changes: dict[int, Reply],
    asked: list[float],
) -> None:
    """Ask at the interval once the alarm stops, and around its new fire time from then.

    The windows start again from the new fire time.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)

    assert (
        await run(hass, aioclient_mock, freezer, replies, asked[-1], changes) == asked
    )


@pytest.mark.usefixtures("google", "window")
@pytest.mark.parametrize(
    ("at", "reply", "asked"),
    [
        # Due 40 s ago when first seen: past the 30 s for it to start ringing
        pytest.param(40, SET, [40 + INTERVAL], id="set"),
        pytest.param(40, answer(alarm(ALARM_SNOOZED)), [40 + INTERVAL], id="snoozed"),
        # Ringing 40 s after its fire time: within the 2-minute window
        pytest.param(40, RINGING, [55, 70, 85, 100, 115, 130, 310], id="ringing"),
        pytest.param(130, RINGING, [130 + INTERVAL], id="ringing-after-window"),
    ],
)
async def test_first_seen_after_fire_time(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    at: float,
    reply: Reply,
    asked: list[float],
) -> None:
    """Count the windows of an alarm first seen after its fire time from that fire time."""
    await start(hass, config_entry, replies, freezer, at, reply)

    assert await run(hass, aioclient_mock, freezer, replies, asked[-1]) == asked


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(HTTPStatus.NOT_FOUND, id="not-found"),
        pytest.param(HTTPStatus.INTERNAL_SERVER_ERROR, id="server-error"),
        pytest.param(TimeoutError(), id="no-answer"),
        pytest.param((HTTPStatus.OK, {}), id="empty"),
        pytest.param(
            (HTTPStatus.OK, {"alarm": [alarm(ALARM_RINGING)]}), id="without-timers"
        ),
    ],
)
async def test_interval_without_alarms_and_timers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    failure: Reply,
) -> None:
    """Ask at the interval after an update that didn't get the alarms and timers.

    The alarm still rings, as the last update that got them showed. Once an update
    gets them again, ask every 15 s again.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    changes = {0: RINGING, 10: failure, 100: RINGING}

    assert await run(hass, aioclient_mock, freezer, replies, 213, changes) == [
        3,
        18,
        18 + INTERVAL,
        33 + INTERVAL,
    ]


@pytest.mark.usefixtures("google")
async def test_interval_after_update_without_token(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Update at the interval after an update that couldn't ask, as the speaker had no token.

    The speaker lost its token while its alarm rang, and got it back later.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 10, {0: RINGING}) == [3]
    device = runtime(config_entry).devices[SPEAKER_ID].data
    assert device is not None
    token, device.auth_token = device.auth_token, None
    assert await run(hass, aioclient_mock, freezer, replies, 100) == []

    device.auth_token = token

    assert await run(hass, aioclient_mock, freezer, replies, 213) == [
        18 + INTERVAL,
        33 + INTERVAL,
    ]


@pytest.mark.usefixtures("google")
async def test_action_answer_during_unanswered_update(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Update at the interval after an unanswered update, although an action got the alarms meanwhile.

    The action's request doesn't count as an answer to the update either.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 17, {0: RINGING}) == [3]
    held = Held(TimeoutError())
    replies[SPEAKER][ALARMS] = held
    replies[SPEAKER][DELETE] = (HTTPStatus.OK, {"success": True})
    device = runtime(config_entry).devices[SPEAKER_ID].data
    assert device is not None

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    # The action finds the alarm still ringing, and deletes the other one
    replies[SPEAKER][ALARMS] = answer(
        alarm(ALARM_RINGING), alarm(ALARM_SET, 600, OTHER_ALARM_ID)
    )
    await hass.services.async_call(
        DOMAIN,
        "delete_alarm",
        {
            ATTR_ENTITY_ID: ALARMS_SENSOR,
            "alarm_id": OTHER_ALARM_ID,
            "skip_refresh": True,
        },
        blocking=True,
    )
    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert device.unanswered_updates == 1

    assert await run(hass, aioclient_mock, freezer, replies, 18 + INTERVAL) == [
        18 + INTERVAL
    ]


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("endpoint", "failure", "asked"),
    [
        # Not answered, which the update handles: it still got the alarms
        pytest.param(DND, TimeoutError(), [3, 18, 33, 48], id="handled"),
        # An answer the update can't read, which fails it
        pytest.param(
            VOLUME,
            (HTTPStatus.OK, {"volume": "loud"}),
            [3, 18, 18 + INTERVAL],
            id="failed",
        ),
    ],
)
async def test_later_request_fails(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    endpoint: str,
    failure: Reply,
    asked: list[float],
) -> None:
    """Keep asking every 15 s after a later request fails, unless that fails the update."""
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 10, {0: RINGING}) == [3]
    replies[SPEAKER][endpoint] = failure

    assert await run(hass, aioclient_mock, freezer, replies, asked[-1]) == asked[1:]


@pytest.mark.usefixtures("google")
async def test_listener_added_during_failing_update(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Update at the interval after a failed update, also when a listener came during it.

    The update got the ringing alarm, then failed on the alarm volume's answer.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 17, {0: RINGING}) == [3]
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    held = Held((HTTPStatus.OK, {"volume": "loud"}))
    replies[SPEAKER][VOLUME] = held

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    coordinator.async_add_listener(lambda: None)
    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    replies[SPEAKER][VOLUME] = SUPPORTED[VOLUME]

    assert await run(hass, aioclient_mock, freezer, replies, 33 + INTERVAL) == [
        18 + INTERVAL,
        33 + INTERVAL,
    ]


@pytest.mark.usefixtures("google", "window")
async def test_unavailable_and_back_within_window(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Make the entities unavailable after 5 unanswered updates, the first one 15 s after the last.

    After the first, the updates are at the interval of 16 s. "Not found" doesn't bring
    them back; an answer with the alarms does, and the updates every 15 s resume.
    """
    await start(hass, config_entry, replies, freezer, -60, SET, interval=16)
    changes = {0: RINGING, 10: TimeoutError(), 90: HTTPStatus.NOT_FOUND, 100: RINGING}
    # At the interval until 3 s after the fire time is sooner
    assert await run(hass, aioclient_mock, freezer, replies, 0, changes) == [
        -44,
        -28,
        -12,
    ]

    assert await run(hass, aioclient_mock, freezer, replies, 82, changes) == [
        3,
        18,
        34,
        50,
        66,
        82,
    ]
    assert state(hass, ALARMS_SENSOR) == STATE_UNAVAILABLE
    assert await run(hass, aioclient_mock, freezer, replies, 98, changes) == [98]
    assert state(hass, ALARMS_SENSOR) == STATE_UNAVAILABLE
    assert await run(hass, aioclient_mock, freezer, replies, 145, changes) == [
        114,
        129,
        145,
    ]
    assert next_alarm_status(hass) == "ringing"


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("at", "asked"),
    # Due 60 s after setup started: asked 3 s after
    # Due 5 s after: past due when setup ends, so asked 5 s after that
    [(60, 63), (5, 15)],
)
async def test_listener_after_setup_waits(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    google: Mock,
    at: int,
    asked: int,
) -> None:
    """Time the first update from when setup ends, when another speaker holds it up 10 s."""
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    held = Held(SUPPORTED[ALARMS])
    replies[BEDROOM] = dict(SUPPORTED) | {ALARMS: held}
    freezer.move_to(datetime.fromtimestamp(FIRE, UTC))
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: INTERVAL}
    )
    replies[SPEAKER][ALARMS] = answer(alarm(ALARM_SET, at))

    setup = hass.async_create_task(set_up(hass, config_entry))
    await held.asked.wait()
    freezer.tick(timedelta(seconds=10))
    replies[BEDROOM][ALARMS] = SUPPORTED[ALARMS]
    held.released.set()
    await setup

    assert await run(hass, aioclient_mock, freezer, replies, asked) == [asked]


@pytest.mark.usefixtures("google")
async def test_interval_changed_while_due(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Keep the update due 3 s after the fire time, and use the new interval after.

    The interval changes once before that update, and once while it waits for an answer.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, -30) == []
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 60}
    )
    held = Held(NONE_LEFT)
    replies[SPEAKER][ALARMS] = held
    assert await run(hass, aioclient_mock, freezer, replies, 2) == []

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 40}
    )
    replies[SPEAKER][ALARMS] = NONE_LEFT
    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert await run(hass, aioclient_mock, freezer, replies, 83) == [43, 83]


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("interval", "asked"),
    [
        (15, [-46, -31, -16, -1, 3, 18, 33, 48]),
        (10, [-51, -41, -31, -21, -11, -1, 3, 13, 23, 33, 43]),
    ],
)
async def test_short_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    interval: int,
    asked: list[float],
) -> None:
    """Ask 3 s after the fire time, and while it rings no more often than the interval."""
    await start(hass, config_entry, replies, freezer, -61, SET, interval)

    assert (
        await run(hass, aioclient_mock, freezer, replies, asked[-1], {0: RINGING})
        == asked
    )


@pytest.mark.usefixtures("google")
async def test_ringing_timer_without_fire_time(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Time the updates from the alarm when a ringing timer has no fire time."""
    reply = answer(alarm(ALARM_SET), timers=(timer(TIMER_RINGING, None),))
    await start(hass, config_entry, replies, freezer, -60, reply)

    assert await run(hass, aioclient_mock, freezer, replies, 33 + INTERVAL - 1) == [
        3,
        8,
        13,
        18,
        23,
        28,
        33,
    ]
    timers = hass.states.get(TIMERS_SENSOR)
    assert timers is not None
    assert timers.attributes["next_timer_status"] == "ringing"


@pytest.mark.usefixtures("google")
async def test_nearest_fire_time(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask around the nearest fire time of a timer or alarm that rings at it.

    The timer rings and is dismissed before the alarm is due. An inactive and a missed
    alarm, and a paused timer, ring at no time.
    """
    others = (
        alarm(ALARM_INACTIVE, 50, OTHER_ALARM_ID),
        alarm(ALARM_MISSED, 60, MISSED_ALARM_ID),
    )
    paused = timer(TIMER_PAUSED, None, PAUSED_TIMER_ID)
    await start(
        hass,
        config_entry,
        replies,
        freezer,
        -60,
        answer(alarm(ALARM_SET, 100), *others, timers=(timer(TIMER_SET), paused)),
    )
    changes = {
        0: answer(
            alarm(ALARM_SET, 100), *others, timers=(timer(TIMER_RINGING), paused)
        ),
        10: answer(alarm(ALARM_SET, 100), *others, timers=(paused,)),
    }

    assert await run(hass, aioclient_mock, freezer, replies, 103, changes) == [
        3,
        18,
        103,
    ]


@pytest.mark.usefixtures("google")
async def test_nothing_asked_when_polling_disabled(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask only at setup around a fire time, while polling is turned off."""
    hass.config_entries.async_update_entry(config_entry, pref_disable_polling=True)
    await start(hass, config_entry, replies, freezer, -60, SET)

    assert await run(hass, aioclient_mock, freezer, replies, 60, {0: RINGING}) == []


@pytest.mark.usefixtures("google")
async def test_nothing_asked_after_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Stop asking once the entry unloads, also before an update due around a fire time."""
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await run(hass, aioclient_mock, freezer, replies, 60, {0: RINGING}) == []
