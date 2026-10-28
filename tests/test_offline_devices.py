"""Tests for updates and actions when a device doesn't answer."""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus
import logging
from unittest.mock import Mock

from aiohttp import ClientConnectorError, ClientPayloadError, ClientTimeout
from glocaltokens.client import Device
import pytest

from custom_components.google_home.button import RebootButton
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber
from custom_components.google_home.sensor import GoogleHomeAlarmsSensor
from custom_components.google_home.switch import DoNotDisturbSwitch

from .test_missing_devices import ALARM_ID, found
from .test_unsupported_devices import (
    ALARMS,
    ALWAYS_LABELS,
    DND,
    EVERYTHING,
    FEATURE_LABELS,
    INFO,
    NEW_TOKEN,
    NO_ALARMS,
    OTHER,
    REBOOT,
    SPEAKER,
    SUPPORTED,
    VOLUME,
    Reply,
    at,
    available,
    entities,
    info,
    poll,
    setup,
)

# A device that doesn't answer: the request times out or can't connect, or the
# answer stops coming after its status
NO_ANSWER = [
    pytest.param(TimeoutError(), id="timeout"),
    pytest.param(ClientConnectorError(Mock(), OSError()), id="offline"),
    pytest.param((HTTPStatus.OK, TimeoutError()), id="answer-timed-out"),
    pytest.param((HTTPStatus.OK, ClientPayloadError("cut off")), id="answer-cut-off"),
]


@pytest.mark.parametrize("error", NO_ANSWER)
@pytest.mark.parametrize(
    ("unanswered", "asked"),
    [
        pytest.param(ALARMS, [ALARMS], id="alarms"),
        pytest.param(VOLUME, [ALARMS, VOLUME], id="alarm-volume"),
    ],
)
def test_update_stops_asking_device_that_doesnt_answer(
    clock: Mock, error: Reply, unanswered: str, asked: list[str]
) -> None:
    """Ask a device nothing more in an update once it doesn't answer, so it costs one timeout.

    Other devices are asked as usual, and the next update asks it again.
    """
    client, _, network = setup({**SUPPORTED, unanswered: error}, SUPPORTED)

    for seconds in (at(0), at(3)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == asked
        assert network.asked(OTHER) == EVERYTHING

    network.replies[SPEAKER] = dict(SUPPORTED)
    poll(client, clock, at(6))
    assert network.asked(SPEAKER) == EVERYTHING


@pytest.mark.parametrize("error", NO_ANSWER)
def test_update_stops_asking_device_when_retry_doesnt_answer(
    clock: Mock, error: Reply
) -> None:
    """Ask a device nothing more in an update when it doesn't answer with its new token either.

    It rejected its token, and Google gave it a new one in the same update.
    """
    client, glocaltokens, network = setup(
        {**SUPPORTED, ALARMS: HTTPStatus.UNAUTHORIZED}
    )

    def google_answers(**_: object) -> list[Device]:
        network.replies[SPEAKER][ALARMS] = error
        return [found("device0", SPEAKER, NEW_TOKEN)]

    glocaltokens.get_google_devices.side_effect = google_answers
    poll(client, clock, at(0))

    assert network.asked(SPEAKER) == [ALARMS, ALARMS]
    assert client.google_devices[0].auth_token == NEW_TOKEN


@pytest.mark.parametrize("error", NO_ANSWER)
def test_update_stops_asking_device_that_doesnt_answer_with_info(
    clock: Mock, error: Reply
) -> None:
    """Ask a device nothing more in an update when it doesn't answer while it's checked for alarms.

    Its alarms answered "not found" 10 minutes ago and again now, so its info is
    asked. That says nothing either way, so later updates and actions ask the
    device as usual.
    """
    client, _, network = setup(NO_ALARMS | {INFO: error})
    poll(client, clock, at(0))
    assert network.asked(SPEAKER) == EVERYTHING

    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    [device] = client.google_devices
    assert not device.alarms_unsupported

    poll(client, clock, at(13))
    assert network.asked(SPEAKER) == EVERYTHING
    asyncio.run(client.reboot_google_device(device))
    assert network.asked(SPEAKER) == [REBOOT]


def test_device_has_5_seconds_to_answer(clock: Mock) -> None:
    """Wait 5 seconds for each answer: a busy device can take more than 2."""
    client, _, network = setup(SUPPORTED)
    poll(client, clock, at(0))
    asyncio.run(client.update_do_not_disturb(client.google_devices[0], enable=True))

    timeouts = [call.kwargs["timeout"] for call in network.session.request.mock_calls]
    assert timeouts == [ClientTimeout(total=5)] * 4


async def turn_on(entity: GoogleHomeBaseEntity) -> None:
    """Turn on Do Not Disturb."""
    assert isinstance(entity, DoNotDisturbSwitch)
    await entity.async_turn_on()


async def set_volume(entity: GoogleHomeBaseEntity) -> None:
    """Set the alarm volume to 40."""
    assert isinstance(entity, AlarmVolumeNumber)
    await entity.async_set_native_value(40)


async def press(entity: GoogleHomeBaseEntity) -> None:
    """Press Reboot."""
    assert isinstance(entity, RebootButton)
    await entity.async_press()


@pytest.mark.parametrize(
    ("label", "act", "sent", "done"),
    [
        pytest.param(
            "Do Not Disturb",
            turn_on,
            DND,
            GoogleHomeDevice.get_do_not_disturb,
            id="do-not-disturb",
        ),
        pytest.param(
            "alarm volume",
            set_volume,
            VOLUME,
            lambda device: device.get_alarm_volume() == 40,
            id="alarm-volume",
        ),
        pytest.param(
            "reboot",
            press,
            REBOOT,
            lambda device: device.available,
            id="reboot",
        ),
    ],
)
def test_action_after_update_device_didnt_answer(
    clock: Mock,
    label: str,
    act: Callable[[GoogleHomeBaseEntity], Awaitable[None]],
    sent: str,
    done: Callable[[GoogleHomeDevice], bool],
) -> None:
    """Send an action to a device that didn't answer the last update.

    Only that update leaves the device's other requests out.
    """
    replies: dict[str, Reply] = dict.fromkeys(SUPPORTED, TimeoutError())
    client, _, network = setup(replies)
    coordinator = Mock(data=poll(client, clock, at(0)))
    assert network.asked(SPEAKER) == [ALARMS]
    [device] = client.google_devices
    assert not device.available

    network.replies[SPEAKER] = dict(SUPPORTED)
    asyncio.run(act(entities(client, coordinator, "device0")[label]))

    assert network.asked(SPEAKER) == [sent]
    assert done(device)


# Where the speaker is after it moves
MOVED = "10.0.0.4"
# Every entity of a device, by label
EVERY_LABEL = FEATURE_LABELS | ALWAYS_LABELS
# What a device answers while it doesn't answer at all, and while it is starting
SILENT: dict[str, Reply] = dict.fromkeys(SUPPORTED, TimeoutError())
STARTING: dict[str, Reply] = dict.fromkeys(SUPPORTED, HTTPStatus.NOT_FOUND)


@pytest.mark.parametrize("error", NO_ANSWER)
def test_unavailable_after_5_updates_without_answer(clock: Mock, error: Reply) -> None:
    """Make a device's alarms, timers and settings unavailable once it doesn't answer 5 updates in a row.

    A speaker that restarts at night doesn't answer a few updates, so fewer don't
    count. Its device sensor and Reboot button stay available, and so does the
    other device. At the next update it answers, they're back with what it has then.
    """
    client, _, network = setup(SUPPORTED, SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    other = entities(client, coordinator, "device1")

    network.replies[SPEAKER] = dict.fromkeys(SUPPORTED, error)
    for update in range(1, 5):
        poll(client, clock, at(0, 15 * update))
        assert available(speaker) == EVERY_LABEL
    poll(client, clock, at(1, 15))
    assert available(speaker) == ALWAYS_LABELS
    assert available(other) == EVERY_LABEL

    # The alarm went off while it didn't answer
    network.replies[SPEAKER] = {
        **SUPPORTED,
        ALARMS: (HTTPStatus.OK, {"alarm": [], "timer": []}),
    }
    poll(client, clock, at(1, 30))
    assert available(speaker) == EVERY_LABEL
    alarms_sensor = speaker["alarms"]
    assert isinstance(alarms_sensor, GoogleHomeAlarmsSensor)
    assert alarms_sensor.extra_state_attributes["alarms"] == []


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(HTTPStatus.INTERNAL_SERVER_ERROR, id="server-error"),
        # Google gives it the same token again
        pytest.param(HTTPStatus.UNAUTHORIZED, id="token-rejected"),
    ],
)
def test_answer_with_error_ends_run(clock: Mock, answer: HTTPStatus) -> None:
    """Keep a device's alarms, timers and settings available while it answers, even with an error.

    Such an answer also ends a run of updates it didn't answer, so the updates
    before it don't add to those after it.
    """
    client, _, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    answering: dict[str, Reply] = dict.fromkeys(SUPPORTED, answer)
    times = iter(range(at(0, 15), at(10), 15))

    for replies in [SILENT] * 4 + [answering] + [SILENT] * 4 + [answering] * 6:
        network.replies[SPEAKER] = dict(replies)
        poll(client, clock, next(times))
        assert available(speaker) == EVERY_LABEL


def test_only_alarms_answer_counts(clock: Mock) -> None:
    """Count only whether a device answers its alarms: a setting that doesn't answer after them doesn't count."""
    client, _, network = setup({**SUPPORTED, VOLUME: TimeoutError()})
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    network.asked(SPEAKER)

    for update in range(1, 7):
        poll(client, clock, at(0, 15 * update))
        assert network.asked(SPEAKER) == [ALARMS, VOLUME]
        assert available(speaker) == EVERY_LABEL


@pytest.mark.parametrize(
    "info_error",
    [
        pytest.param(TimeoutError(), id="info-timeout"),
        pytest.param(ClientConnectorError(Mock(), OSError()), id="info-offline"),
    ],
)
@pytest.mark.parametrize(
    ("silent", "shown", "next_replies"),
    [
        # It stays unavailable, and is back at the next update with its alarms
        pytest.param(5, ALWAYS_LABELS, SUPPORTED, id="unavailable"),
        # The run ends, so one more update without an answer starts a new one
        pytest.param(4, EVERY_LABEL, SILENT, id="run-of-4"),
    ],
)
def test_not_found_when_info_doesnt_answer(
    clock: Mock,
    info_error: Exception,
    silent: int,
    shown: set[str],
    next_replies: dict[str, Reply],
) -> None:
    """Count a "not found" answer to alarms, also when the device then doesn't answer when asked for its info.

    It ends a shorter run of updates the device didn't answer, but doesn't bring
    back what a run made unavailable. Checking whether it has alarms works as
    before: its info is asked, and it isn't taken to have none.
    """
    client, _, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    not_found = {**SUPPORTED, ALARMS: HTTPStatus.NOT_FOUND, INFO: info_error}
    # Its info is asked if its alarms still answer "not found" 10 minutes later.
    # Until then, updates it doesn't answer keep the check going.
    network.replies[SPEAKER] = not_found
    poll(client, clock, at(0, 15))
    network.replies[SPEAKER] = dict(SILENT)
    for update in range(silent):
        poll(client, clock, at(1, 15 * update))
    assert available(speaker) == shown
    network.asked(SPEAKER)

    network.replies[SPEAKER] = not_found
    poll(client, clock, at(10, 15))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert available(speaker) == shown
    network.replies[SPEAKER] = dict(next_replies)
    poll(client, clock, at(10, 30))

    assert available(speaker) == EVERY_LABEL
    assert not client.google_devices[0].alarms_unsupported


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(HTTPStatus.INTERNAL_SERVER_ERROR, id="server-error"),
        # Google gives it the same token again
        pytest.param(HTTPStatus.UNAUTHORIZED, id="token-rejected"),
        pytest.param((HTTPStatus.OK, {}), id="not-alarms"),
    ],
)
def test_available_again_without_new_alarms(clock: Mock, answer: Reply) -> None:
    """Make a device's alarms, timers and settings available again when it answers, even without its alarms.

    They show the values they had.
    """
    client, _, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    network.replies[SPEAKER] = dict(SILENT)
    for update in range(1, 6):
        poll(client, clock, at(0, 15 * update))
    assert available(speaker) == ALWAYS_LABELS

    network.replies[SPEAKER] = dict.fromkeys(SUPPORTED, answer)
    poll(client, clock, at(1, 30))

    assert available(speaker) == EVERY_LABEL
    alarms_sensor = speaker["alarms"]
    assert isinstance(alarms_sensor, GoogleHomeAlarmsSensor)
    shown = alarms_sensor.extra_state_attributes["alarms"]
    assert [alarm["alarm_id"] for alarm in shown] == [ALARM_ID]


def test_address_from_mdns_isnt_an_answer(clock: Mock) -> None:
    """Keep a device's alarms, timers and settings unavailable when mDNS reports its address.

    Only an update it answers brings them back: it may still be starting, or not
    answer at that address either.
    """
    client, _, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    [device] = client.google_devices
    # Google's ID for it, which mDNS reports too
    device.cloud_device_id = "device0"
    network.replies[SPEAKER] = dict(SILENT)
    for update in range(1, 6):
        poll(client, clock, at(0, 15 * update))
    assert available(speaker) == ALWAYS_LABELS

    network.replies[MOVED] = dict(SILENT)
    client.found_devices.async_device_found("device0", "Device 0", MOVED)
    assert device.ip_address == MOVED
    assert available(speaker) == ALWAYS_LABELS
    poll(client, clock, at(1, 30))
    assert network.asked(MOVED) == [ALARMS]
    assert available(speaker) == ALWAYS_LABELS

    network.replies[MOVED] = dict(SUPPORTED)
    poll(client, clock, at(1, 45))
    assert available(speaker) == EVERY_LABEL


def test_stay_unavailable_while_starting(clock: Mock) -> None:
    """Keep a device's alarms, timers and settings unavailable while it answers "not found" as it starts.

    A speaker that was off answers "not found" to every request of an update for
    a while, then rejects its old token. Google gives it a new one, and its alarms
    are back in that update.
    """
    client, glocaltokens, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    network.replies[SPEAKER] = dict(SILENT)
    for update in range(1, 6):
        poll(client, clock, at(0, 15 * update))
    assert available(speaker) == ALWAYS_LABELS

    network.replies[SPEAKER] = dict(STARTING)
    network.asked(SPEAKER)
    for update in range(6, 8):
        poll(client, clock, at(0, 15 * update))
        assert network.asked(SPEAKER) == EVERYTHING
        assert available(speaker) == ALWAYS_LABELS

    def google_answers(**_: object) -> list[Device]:
        # The alarm went off while it was off
        network.replies[SPEAKER] = {
            **SUPPORTED,
            ALARMS: (HTTPStatus.OK, {"alarm": [], "timer": []}),
        }
        return [found("device0", SPEAKER, NEW_TOKEN)]

    glocaltokens.get_google_devices.side_effect = google_answers
    network.replies[SPEAKER] = {**SUPPORTED, ALARMS: HTTPStatus.UNAUTHORIZED}
    poll(client, clock, at(2))

    assert client.google_devices[0].auth_token == NEW_TOKEN
    assert available(speaker) == EVERY_LABEL
    alarms_sensor = speaker["alarms"]
    assert isinstance(alarms_sensor, GoogleHomeAlarmsSensor)
    assert alarms_sensor.extra_state_attributes["alarms"] == []


@pytest.mark.parametrize(
    "updates",
    [
        # As speakers that restarted at night answered
        pytest.param([SILENT] * 3 + [STARTING, SUPPORTED], id="restart"),
        pytest.param(
            [SILENT] * 4 + [STARTING] + [SILENT] * 4 + [SUPPORTED], id="two-restarts"
        ),
    ],
)
def test_not_found_ends_run(clock: Mock, updates: list[dict[str, Reply]]) -> None:
    """Keep a device's alarms, timers and settings available when "not found" ends a run of fewer than 5 updates.

    A speaker that restarts doesn't answer a few updates, then answers "not found"
    while it starts.
    """
    client, _, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")

    for update, replies in enumerate(updates, start=1):
        network.replies[SPEAKER] = dict(replies)
        poll(client, clock, at(0, 15 * update))
        assert available(speaker) == EVERY_LABEL


def test_unavailable_until_found_without_alarms(clock: Mock) -> None:
    """Count a device whose alarms answer "not found" or nothing until it turns out to have none.

    Its settings answer, so it can have these entities. "Not found" ends each run of
    updates it didn't answer, so only 5 in a row make them unavailable, and they
    stay so while it answers "not found". Once its info shows no Google Assistant,
    they stay unavailable for that reason, and it's asked nothing more.
    """
    replies: dict[str, Reply] = {
        **SUPPORTED,
        ALARMS: HTTPStatus.NOT_FOUND,
        INFO: info(),
    }
    client, _, network = setup(replies)
    # The first "not found" starts the 10 minutes before its info is asked
    coordinator = Mock(data=poll(client, clock, at(0)))
    speaker = entities(client, coordinator, "device0")
    times = iter(range(at(0, 15), at(10), 15))

    alternating: list[Reply] = [TimeoutError(), HTTPStatus.NOT_FOUND] * 3
    for alarms in alternating + [TimeoutError()] * 4:
        network.replies[SPEAKER][ALARMS] = alarms
        poll(client, clock, next(times))
        assert available(speaker) == EVERY_LABEL
    poll(client, clock, next(times))
    assert available(speaker) == ALWAYS_LABELS
    network.replies[SPEAKER][ALARMS] = HTTPStatus.NOT_FOUND
    poll(client, clock, next(times))
    assert available(speaker) == ALWAYS_LABELS
    network.asked(SPEAKER)

    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported
    for seconds in (at(10, 15), at(11)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == []
        assert available(speaker) == ALWAYS_LABELS


def test_log_when_unavailable_and_back(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log once when a device's alarms, timers and settings become unavailable, and once when they're back.

    "Not found" while it starts doesn't bring them back, so nothing is logged then.
    """
    caplog.set_level(logging.INFO)
    client, _, network = setup(SUPPORTED)
    times = iter(range(at(0), at(10), 15))
    poll(client, clock, next(times))

    for replies in [SILENT] * 7 + [STARTING] + [SUPPORTED] * 2:
        network.replies[SPEAKER] = dict(replies)
        poll(client, clock, next(times))

    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == [
        (
            "Device 0 didn't answer 5 updates in a row. Its alarms, timers and "
            "settings are unavailable until it answers with something other than "
            '"not found".'
        ),
        "Device 0 answers again. Its alarms, timers and settings are available.",
    ]
