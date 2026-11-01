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
    API_ENDPOINT_BUILD_INFO,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    FIRMWARE_CHECK_INTERVAL,
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


def alarms_asked(
    aioclient_mock: AiohttpClientMocker, endpoint: str = API_ENDPOINT_ALARMS
) -> bool:
    """Return whether the speaker was asked for its alarms since the last call.

    Or for what the given endpoint has.
    """
    asked = any(
        method.upper() == "GET"
        and url.host == SPEAKER
        and url.path_qs.removeprefix("/") == endpoint
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
    endpoint: str = API_ENDPOINT_ALARMS,
) -> list[float]:
    """Move the clock a second at a time, to this many seconds after FIRE.

    At each change's time, before the updates due then, the speaker starts answering
    the alarms request with its reply. Return when the speaker was asked for its alarms,
    or for what the given endpoint has.
    """
    changes = changes or {}
    asked: list[float] = []
    alarms_asked(aioclient_mock, endpoint)
    while seconds() < until:
        freezer.tick(timedelta(seconds=1))
        reply = changes.get(int(now)) if (now := seconds()).is_integer() else None
        if reply is not None:
            replies[SPEAKER][ALARMS] = reply
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
        if alarms_asked(aioclient_mock, endpoint):
            asked.append(seconds())
    return asked


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("at", "asked"),
    [
        # 61 s before the next update at the interval
        pytest.param(-60, [1, 6, 11, 16, 21, 26, 31, 211], id="due-before-next-update"),
        # The next update, at -120, comes first
        pytest.param(
            -300, [-120, 1, 6, 11, 16, 21, 26, 31, 211], id="due-after-next-update"
        ),
        # The update at the interval comes at the fire time, so it's the first after it
        pytest.param(-180, [0, 5, 10, 15, 20, 25, 30, 210], id="update-at-fire-time"),
        # The update for 1 s after the fire time comes 0.4 s early, as it can when it's
        # timed from a fraction of a second, and finds the alarm still set
        pytest.param(
            -59.4,
            [0.6, 5.6, 10.6, 15.6, 20.6, 25.6, 30.6, 210.6],
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
    """Ask a speaker 1 s after its alarm's fire time, then every 5 s while it isn't ringing.

    Until an update at least 30 s after the fire time, then at the interval again. An
    update that comes before the one for 1 s after doesn't replace it, and the first
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
    """Ask every 10 s while the alarm rings, and show its dismissal at the next update."""
    await start(hass, config_entry, replies, freezer, -60, SET)
    changes = {0: RINGING, 40: NONE_LEFT}

    assert await run(hass, aioclient_mock, freezer, replies, 1, changes) == [1]
    assert next_alarm_status(hass) == "ringing"
    assert await run(hass, aioclient_mock, freezer, replies, 40, changes) == [
        11,
        21,
        31,
    ]
    assert next_alarm_status(hass) == "ringing"
    assert await run(hass, aioclient_mock, freezer, replies, 41 + INTERVAL) == [
        41,
        41 + INTERVAL,
    ]
    assert next_alarm_status(hass) == "none"


@pytest.mark.usefixtures("google", "window")
@pytest.mark.parametrize(
    ("changes", "asked", "status"),
    [
        # Dismissed after the last update every 10 s before the end of the window, and
        # shown by the update after the end
        pytest.param(
            {0: RINGING, 115: NONE_LEFT},
            [1, 11, 21, 31, 41, 51, 61, 71, 81, 91, 101, 111, 121, 301, 481],
            "none",
            id="dismissed-before-end",
        ),
        pytest.param(
            {0: RINGING},
            [1, 11, 21, 31, 41, 51, 61, 71, 81, 91, 101, 111, 121, 301, 481],
            "ringing",
            id="rings-on",
        ),
        # The speaker reports a later fire time at every update while it rings, which
        # doesn't move the end of the window
        pytest.param(
            {at: answer(alarm(ALARM_RINGING, at)) for at in range(482)},
            [1, 11, 21, 31, 41, 51, 61, 71, 81, 91, 101, 111, 121, 301, 481],
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
    """Ask every 10 s while the alarm rings, until an update after the end of its window.

    Then at the interval while it still rings.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)

    assert await run(hass, aioclient_mock, freezer, replies, 481, changes) == asked
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

    Also when that update finishes after it. The alarm starts ringing 28 s after its
    fire time, and is dismissed 1 s after the last update every 10 s asked for it. If
    the next update gets no answer, it shows nothing, and the next one is at the interval.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    changes = {28: RINGING}

    assert await run(hass, aioclient_mock, freezer, replies, 110, changes) == [
        1,
        6,
        11,
        16,
        21,
        26,
        31,
        41,
        51,
        61,
        71,
        81,
        91,
        101,
    ]
    # Asked at 111 s, while it still rang
    await hold_dnd(hass, replies, freezer, 10, then)
    assert alarms_asked(aioclient_mock)
    assert seconds() == 121
    assert await run(hass, aioclient_mock, freezer, replies, 131 + INTERVAL) == [
        131,
        131 + INTERVAL,
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

    assert await run(hass, aioclient_mock, freezer, replies, 25) == [1, 6, 11, 16, 21]
    # Asked at 26 s, while it was still set
    await hold_dnd(hass, replies, freezer, 5, RINGING)
    assert seconds() == 31
    assert await run(hass, aioclient_mock, freezer, replies, 46) == [36, 46]
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
    assert await run(hass, aioclient_mock, freezer, replies, 0, {0: RINGING}) == []
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
            [1, 11, 21, 201, 381, 561, 601, 606, 616, 626],
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
            [1, 11, 21, 201, 381, 561, 601, 611, 621],
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
        pytest.param(
            40, RINGING, [50, 60, 70, 80, 90, 100, 110, 120, 300], id="ringing"
        ),
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
    gets them again, ask every 10 s again.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    changes = {0: RINGING, 10: failure, 100: RINGING}

    assert await run(hass, aioclient_mock, freezer, replies, 201, changes) == [
        1,
        11,
        11 + INTERVAL,
        21 + INTERVAL,
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
    assert await run(hass, aioclient_mock, freezer, replies, 5, {0: RINGING}) == [1]
    device = runtime(config_entry).devices[SPEAKER_ID].data
    assert device is not None
    token, device.auth_token = device.auth_token, None
    assert await run(hass, aioclient_mock, freezer, replies, 100) == []

    device.auth_token = token

    assert await run(hass, aioclient_mock, freezer, replies, 201) == [
        11 + INTERVAL,
        21 + INTERVAL,
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
    assert await run(hass, aioclient_mock, freezer, replies, 10, {0: RINGING}) == [1]
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

    assert await run(hass, aioclient_mock, freezer, replies, 11 + INTERVAL) == [
        11 + INTERVAL
    ]


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("endpoint", "failure", "asked"),
    [
        # Not answered, which the update handles: it still got the alarms
        pytest.param(DND, TimeoutError(), [1, 11, 21, 31], id="handled"),
        # An answer the update can't read, which fails it
        pytest.param(
            VOLUME,
            (HTTPStatus.OK, {"volume": "loud"}),
            [1, 11, 11 + INTERVAL],
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
    """Keep asking every 10 s after a later request fails, unless that fails the update."""
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 5, {0: RINGING}) == [1]
    replies[SPEAKER][endpoint] = failure

    assert await run(hass, aioclient_mock, freezer, replies, asked[-1]) == asked[1:]


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("endpoint", "reply", "then"),
    [
        # The update gets no answer for the alarms, which it handles
        pytest.param(ALARMS, TimeoutError(), RINGING, id="not-answered"),
        # The update gets the ringing alarm, then fails on the alarm volume's answer
        pytest.param(
            VOLUME,
            (HTTPStatus.OK, {"volume": "loud"}),
            SUPPORTED[VOLUME],
            id="failed",
        ),
    ],
)
async def test_listener_added_during_update_without_alarms(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    endpoint: str,
    reply: Reply,
    then: Reply,
) -> None:
    """Update at the interval after an update that didn't get the alarms and timers.

    Also when a listener came during it, while the alarm still rang as the last update
    that got them showed.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, 10, {0: RINGING}) == [1]
    coordinator = runtime(config_entry).devices[SPEAKER_ID]
    held = Held(reply)
    replies[SPEAKER][endpoint] = held

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    coordinator.async_add_listener(lambda: None)
    replies[SPEAKER][endpoint] = then
    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert await run(hass, aioclient_mock, freezer, replies, 21 + INTERVAL) == [
        11 + INTERVAL,
        21 + INTERVAL,
    ]


@pytest.mark.usefixtures("google", "window")
async def test_unavailable_and_back_within_window(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Make the entities unavailable after 5 unanswered updates, the first one 10 s after the last.

    After the first, the updates are at the interval of 16 s. "Not found" doesn't bring
    them back; an answer with the alarms does, and the updates every 10 s resume.
    """
    await start(hass, config_entry, replies, freezer, -60, SET, interval=16)
    changes = {0: RINGING, 10: TimeoutError(), 90: HTTPStatus.NOT_FOUND, 100: RINGING}
    # At the interval until 1 s after the fire time is sooner
    assert await run(hass, aioclient_mock, freezer, replies, 0, changes) == [
        -44,
        -28,
        -12,
    ]

    assert await run(hass, aioclient_mock, freezer, replies, 75, changes) == [
        1,
        11,
        27,
        43,
        59,
        75,
    ]
    assert state(hass, ALARMS_SENSOR) == STATE_UNAVAILABLE
    assert await run(hass, aioclient_mock, freezer, replies, 91, changes) == [91]
    assert state(hass, ALARMS_SENSOR) == STATE_UNAVAILABLE
    assert await run(hass, aioclient_mock, freezer, replies, 143, changes) == [
        107,
        117,
        127,
        143,
    ]
    assert next_alarm_status(hass) == "ringing"


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("at", "asked"),
    # Due 60 s after setup started: asked 1 s after
    # Due 5 s after: past due when setup ends, so asked 5 s after that
    [(60, 61), (5, 15)],
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
    replies[BEDROOM] = {**SUPPORTED, ALARMS: held}
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
    """Keep the update due 1 s after the fire time, and use the new interval after.

    The interval changes once before that update, and once while it waits for an answer.
    """
    await start(hass, config_entry, replies, freezer, -60, SET)
    assert await run(hass, aioclient_mock, freezer, replies, -30) == []
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 60}
    )
    held = Held(NONE_LEFT)
    replies[SPEAKER][ALARMS] = held
    assert await run(hass, aioclient_mock, freezer, replies, 0) == []

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await held.asked.wait()
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 40}
    )
    replies[SPEAKER][ALARMS] = NONE_LEFT
    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert await run(hass, aioclient_mock, freezer, replies, 81) == [41, 81]


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("interval", "asked"),
    [
        # More often than the interval while it rings
        (15, [-46, -31, -16, -1, 1, 11, 21, 31, 41]),
        # As often as the interval
        (10, [-51, -41, -31, -21, -11, -1, 1, 11, 21, 31, 41]),
        # At the interval, which is shorter
        (8, [-53, -45, -37, -29, -21, -13, -5, 1, 9, 17, 25, 33, 41]),
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
    """Ask 1 s after the fire time, and while it rings every 10 s, or at a shorter interval."""
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

    assert await run(hass, aioclient_mock, freezer, replies, 31 + INTERVAL - 1) == [
        1,
        6,
        11,
        16,
        21,
        26,
        31,
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

    assert await run(hass, aioclient_mock, freezer, replies, 101, changes) == [
        1,
        11,
        101,
    ]


@pytest.mark.usefixtures("google")
async def test_firmware_checked_every_20_minutes_while_ringing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask for the firmware only once a check is due, also while asking every 10 s.

    Setup checked it 20 minutes less 50 s before the fire time, so the next check is
    due 50 s after it: at the update every 10 s at 51 s. The one after is due 20 minutes
    after that check started, again at an update every 10 s.
    """
    # The client times the checks with monotonic, which freezegun replaces only in some
    # orders of the tests that ran before: use the event loop's time, which it moves
    with patch("custom_components.google_home.api.monotonic", hass.loop.time):
        await start(
            hass, config_entry, replies, freezer, 50 - FIRMWARE_CHECK_INTERVAL, SET
        )

        assert await run(
            hass,
            aioclient_mock,
            freezer,
            replies,
            51 + FIRMWARE_CHECK_INTERVAL,
            {0: RINGING},
            API_ENDPOINT_BUILD_INFO,
        ) == [51, 51 + FIRMWARE_CHECK_INTERVAL]


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
