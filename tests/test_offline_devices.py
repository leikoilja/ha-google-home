"""Tests for updates and actions when a device doesn't answer."""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus
import logging
from unittest.mock import Mock

from aiohttp import (
    ClientConnectorError,
    ClientPayloadError,
    ClientTimeout,
    ContentTypeError,
)
from glocaltokens.client import Device
import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.button import RebootButton
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
)
from custom_components.google_home.switch import DoNotDisturbSwitch

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.helpers.aiohttp_client import SSRFRedirectError

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
    WITH_INFO,
    Network,
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
        # Its info is asked once after its alarms, for its available attribute
        pytest.param(ALARMS, [ALARMS, INFO], id="alarms"),
        pytest.param(VOLUME, [ALARMS, VOLUME], id="alarm-volume"),
    ],
)
def test_update_stops_asking_device_that_doesnt_answer(
    clock: Mock, error: Reply, unanswered: str, asked: list[str]
) -> None:
    """Ask a device nothing more in an update once it doesn't answer, but its info once after its alarms.

    So it costs at most two timeouts, not four. Other devices are asked as usual,
    and the next update asks it again.
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
    """Ask a device only for its info in the rest of an update when it doesn't answer with its new token either.

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

    assert network.asked(SPEAKER) == [ALARMS, ALARMS, INFO]
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
    assert network.asked(SPEAKER) == WITH_INFO

    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    [device] = client.google_devices
    assert not device.alarms_unsupported

    poll(client, clock, at(13))
    assert network.asked(SPEAKER) == WITH_INFO
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
            lambda device: device.do_not_disturb,
            id="do-not-disturb",
        ),
        pytest.param(
            "alarm volume",
            set_volume,
            VOLUME,
            lambda device: device.alarm_volume == 40,
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
    assert network.asked(SPEAKER) == [ALARMS, INFO]
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
    """Make all of a device's entities unavailable once it doesn't answer 5 updates in a row.

    A speaker that restarts at night doesn't answer a few updates, so fewer don't
    count. The other device stays available. At the next update it answers, they're
    all back, with what it has then.
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
    assert available(speaker) == set()
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
        pytest.param(5, set(), SUPPORTED, id="unavailable"),
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
    assert available(speaker) == set()

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
    assert available(speaker) == set()

    network.replies[MOVED] = dict(SILENT)
    client.found_devices.async_device_found("device0", "Device 0", MOVED)
    assert device.ip_address == MOVED
    assert available(speaker) == set()
    poll(client, clock, at(1, 30))
    assert network.asked(MOVED) == [ALARMS, INFO]
    assert available(speaker) == set()

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
    assert available(speaker) == set()

    network.replies[SPEAKER] = dict(STARTING)
    network.asked(SPEAKER)
    for update in range(6, 8):
        poll(client, clock, at(0, 15 * update))
        assert network.asked(SPEAKER) == WITH_INFO
        assert available(speaker) == set()

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


@pytest.mark.parametrize(
    ("probe", "shown"),
    [
        pytest.param(info(), ALWAYS_LABELS, id="answers"),
        pytest.param(TimeoutError(), set(), id="doesnt-answer"),
    ],
)
def test_unavailable_until_found_without_alarms(
    clock: Mock, probe: Reply, shown: set[str]
) -> None:
    """Count a device whose alarms answer "not found" or nothing until it turns out to have none.

    Its settings answer, so it can have these entities. "Not found" ends each run of
    updates it didn't answer, so only 5 in a row make them unavailable, and they
    stay so while it answers "not found", also when its info shows no Google
    Assistant. From the next update, it's asked only for its info: an answer brings
    back its device sensor and reboot button, while its alarms, timers and settings
    stay unavailable.
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
    assert available(speaker) == set()
    network.replies[SPEAKER][ALARMS] = HTTPStatus.NOT_FOUND
    poll(client, clock, next(times))
    assert available(speaker) == set()
    network.asked(SPEAKER)

    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported
    assert available(speaker) == set()
    network.replies[SPEAKER][INFO] = probe
    for seconds in (at(10, 15), at(10, 30)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == [INFO]
        assert available(speaker) == shown


def without_alarms(
    clock: Mock,
) -> tuple[GlocaltokensApiClient, Mock, Network, dict[str, GoogleHomeBaseEntity]]:
    """Return a client whose device has turned out to have no alarms, as at 10 minutes.

    Also return its fake glocaltokens, the network and the device's entities. What
    the device was asked so far is forgotten.
    """
    client, glocaltokens, network = setup(NO_ALARMS)
    coordinator = Mock(data=poll(client, clock, at(0)))
    poll(client, clock, at(10))
    assert client.google_devices[0].alarms_unsupported
    network.asked(SPEAKER)
    network.gets.clear()
    return client, glocaltokens, network, entities(client, coordinator, "device0")


def go_silent(
    client: GlocaltokensApiClient, clock: Mock, network: Network, updates: int
) -> None:
    """Run this many updates, from 10:15, in which the device's info times out."""
    network.replies[SPEAKER][INFO] = TimeoutError()
    for update in range(1, updates + 1):
        poll(client, clock, at(10, 15 * update))


def test_device_without_alarms_asked_for_info(clock: Mock) -> None:
    """Ask a device without alarms for its info once an update, without its token, and nothing else.

    Redirects aren't followed.
    """
    client, _, network, _ = without_alarms(clock)
    for seconds in (at(10, 15), at(10, 30), at(10, 45)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == [INFO]

    url = "https://10.0.0.2:8443/setup/eureka_info?params=name,device_info"
    options = {"timeout": ClientTimeout(total=5), "allow_redirects": False}
    assert network.gets == [(url, options)] * 3


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError(), id="timeout"),
        pytest.param(ClientConnectorError(Mock(), OSError()), id="offline"),
        # The session rejects a redirect to a blocked address before the answer
        # reaches the integration
        pytest.param(SSRFRedirectError("blocked"), id="redirect-rejected"),
    ],
)
def test_device_without_alarms_unavailable_while_info_doesnt_answer(
    clock: Mock, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """Make a device without alarms unavailable once its info doesn't answer 5 updates in a row.

    Its device sensor and reboot button are back at the next answer. Its alarms,
    timers and settings stay unavailable throughout.
    """
    client, _, network, chromecast = without_alarms(clock)
    network.replies[SPEAKER][INFO] = error
    caplog.set_level(logging.DEBUG)
    for update in range(1, 5):
        poll(client, clock, at(10, 15 * update))
        assert available(chromecast) == ALWAYS_LABELS
    poll(client, clock, at(11, 15))
    assert available(chromecast) == set()
    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().endswith("when asked for its info")
    ] == ["Device 0 didn't answer when asked for its info"] * 5

    network.replies[SPEAKER][INFO] = info()
    poll(client, clock, at(11, 30))
    assert available(chromecast) == ALWAYS_LABELS


@pytest.mark.parametrize(
    ("reply", "close_error", "shown"),
    [
        pytest.param(
            (HTTPStatus.OK, TimeoutError()), None, set(), id="200-body-times-out"
        ),
        pytest.param(
            (HTTPStatus.OK, ClientPayloadError("cut off")),
            None,
            set(),
            id="200-body-cut-off",
        ),
        pytest.param(
            (HTTPStatus.OK, b"<html>"), None, ALWAYS_LABELS, id="200-not-json"
        ),
        pytest.param(HTTPStatus.NOT_FOUND, None, set(), id="404-holds"),
        pytest.param(
            (HTTPStatus.INTERNAL_SERVER_ERROR, ClientPayloadError("cut off")),
            None,
            ALWAYS_LABELS,
            id="500-body-fails",
        ),
        pytest.param(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            ClientPayloadError("closed"),
            ALWAYS_LABELS,
            id="500-close-fails",
        ),
        pytest.param(HTTPStatus.FOUND, None, ALWAYS_LABELS, id="302"),
    ],
)
def test_info_answer_after_device_without_alarms_was_unavailable(
    clock: Mock, reply: Reply, close_error: Exception | None, shown: set[str]
) -> None:
    """Count an info answer as the integration receives it.

    A 200 counts once its body has come, whatever it is. Another status counts as
    soon as it comes, even if its body or closing then fails. A redirect that
    reaches the integration is an answer.
    """
    client, _, network, chromecast = without_alarms(clock)
    go_silent(client, clock, network, 5)
    assert available(chromecast) == set()

    network.replies[SPEAKER][INFO] = reply
    if close_error:
        network.close_errors[SPEAKER] = close_error
    poll(client, clock, at(11, 30))

    assert network.asked(SPEAKER)[-1:] == [INFO]
    assert available(chromecast) == shown


@pytest.mark.parametrize(
    ("reply", "close_error"),
    [
        pytest.param(
            (HTTPStatus.NOT_FOUND, ClientPayloadError("cut off")),
            None,
            id="body-fails",
        ),
        pytest.param(
            HTTPStatus.NOT_FOUND, ClientPayloadError("closed"), id="close-fails"
        ),
    ],
)
def test_info_not_found_ends_run_of_device_without_alarms(
    clock: Mock, reply: Reply, close_error: Exception
) -> None:
    """End a run of updates without an answer when a device without alarms answers "not found" to its info.

    Even if its body or closing then fails: the updates before it don't add to those
    after it.
    """
    client, _, network, chromecast = without_alarms(clock)
    go_silent(client, clock, network, 4)

    network.replies[SPEAKER][INFO] = reply
    if close_error:
        network.close_errors[SPEAKER] = close_error
    poll(client, clock, at(11, 15))
    network.close_errors.clear()
    network.replies[SPEAKER][INFO] = TimeoutError()
    poll(client, clock, at(11, 30))

    assert available(chromecast) == ALWAYS_LABELS


def test_info_counted_once_per_call(clock: Mock) -> None:
    """Count each update's info call once, from how it ends.

    The session may try once more inside one call after a lost connection; the
    integration sees only the call's outcome. So an update counts once, also when
    the call ends with an answer.
    """
    client, _, network, chromecast = without_alarms(clock)
    go_silent(client, clock, network, 4)
    network.replies[SPEAKER][INFO] = info()
    poll(client, clock, at(11, 15))
    assert network.asked(SPEAKER) == [INFO] * 5

    network.replies[SPEAKER][INFO] = TimeoutError()
    for seconds in range(at(11, 30), at(12, 30), 15):
        poll(client, clock, seconds)
        assert available(chromecast) == ALWAYS_LABELS
    poll(client, clock, at(12, 30))
    assert available(chromecast) == set()


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(HTTPStatus.UNAUTHORIZED, id="401"),
        pytest.param(HTTPStatus.SERVICE_UNAVAILABLE, id="503"),
    ],
)
def test_info_error_answer_without_new_token(clock: Mock, status: HTTPStatus) -> None:
    """Count an error answer to a device's info as an answer, without asking Google for a token.

    The request has no token, so there's none to replace, and it isn't sent again.
    """
    client, glocaltokens, network, chromecast = without_alarms(clock)
    fetches = glocaltokens.get_google_devices.call_count
    go_silent(client, clock, network, 5)
    network.asked(SPEAKER)

    network.replies[SPEAKER][INFO] = status
    poll(client, clock, at(11, 30))

    assert network.asked(SPEAKER) == [INFO]
    assert available(chromecast) == ALWAYS_LABELS
    assert glocaltokens.get_google_devices.call_count == fetches
    assert client.google_devices_fetched


def test_device_without_alarms_or_token_asked_for_info(clock: Mock) -> None:
    """Ask a device without alarms for its info even when Google gives it no token.

    It isn't asked for alarms, and Google isn't asked for a token.
    """
    client, glocaltokens, network, chromecast = without_alarms(clock)
    client.google_devices[0].auth_token = None
    fetches = glocaltokens.get_google_devices.call_count
    go_silent(client, clock, network, 5)
    assert network.asked(SPEAKER) == [INFO] * 5
    assert available(chromecast) == set()

    network.replies[SPEAKER][INFO] = info()
    poll(client, clock, at(11, 30))

    assert network.asked(SPEAKER) == [INFO]
    assert available(chromecast) == ALWAYS_LABELS
    assert glocaltokens.get_google_devices.call_count == fetches


def test_no_request_without_token_or_address(clock: Mock) -> None:
    """Ask nothing of a device with alarms but no token, nor of a device without an address."""
    client, _, network = setup(SUPPORTED, NO_ALARMS)
    poll(client, clock, at(0))
    poll(client, clock, at(10))
    speaker, chromecast = client.google_devices
    assert chromecast.alarms_unsupported
    speaker.auth_token = None
    chromecast.ip_address = None
    network.asked(SPEAKER)
    network.asked(OTHER)

    poll(client, clock, at(10, 15))

    assert network.asked(SPEAKER) == []
    assert network.asked(OTHER) == []


def device_sensor(
    client: GlocaltokensApiClient, coordinator: Mock
) -> GoogleHomeDeviceSensor:
    """Return the device sensor of the device at SPEAKER."""
    sensor = entities(client, coordinator, "device0")["device"]
    assert isinstance(sensor, GoogleHomeDeviceSensor)
    return sensor


@pytest.mark.parametrize(
    ("replies", "asked", "shown"),
    [
        # Its info isn't asked then
        pytest.param(SUPPORTED, EVERYTHING, True, id="alarms-200"),
        # As a speaker answers while it starts, while its info already answers or
        # not yet
        pytest.param(STARTING | {INFO: info()}, WITH_INFO, True, id="404-info-200"),
        pytest.param(STARTING, WITH_INFO, False, id="404-info-404"),
        pytest.param(
            {**dict.fromkeys(SUPPORTED, HTTPStatus.UNAUTHORIZED), INFO: info()},
            WITH_INFO,
            True,
            id="token-rejected-info-200",
        ),
        pytest.param(
            {**dict.fromkeys(SUPPORTED, HTTPStatus.SERVICE_UNAVAILABLE), INFO: info()},
            WITH_INFO,
            True,
            id="503-info-200",
        ),
        # Its info counts once its body has come
        pytest.param(
            STARTING | {INFO: (HTTPStatus.OK, TimeoutError())},
            WITH_INFO,
            False,
            id="404-info-body-timed-out",
        ),
        pytest.param(
            SILENT | {INFO: info()}, [ALARMS, INFO], True, id="silent-info-200"
        ),
        pytest.param(SILENT, [ALARMS, INFO], False, id="silent"),
    ],
)
def test_available_attribute_from_alarms_or_info(
    clock: Mock, replies: dict[str, Reply], asked: list[str], shown: bool
) -> None:
    """Show in the available attribute whether a speaker's alarms answer 200, or else its info does.

    Its info is asked at most once an update, without its token, and only when its
    alarms don't answer 200. Each case starts from the other value.
    """
    client, _, network = setup(SILENT if shown else SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    sensor = device_sensor(client, coordinator)
    attribute = [sensor.extra_state_attributes["available"]]
    network.asked(SPEAKER)

    network.replies[SPEAKER] = dict(replies)
    poll(client, clock, at(0, 15))
    attribute.append(sensor.extra_state_attributes["available"])

    assert network.asked(SPEAKER) == asked
    assert attribute == [not shown, shown]
    assert sensor.available


@pytest.mark.parametrize(
    ("reply", "shown", "asked"),
    [
        # Its info lists no Google Assistant: it's marked as having no alarms
        pytest.param(info(), True, [ALARMS, INFO], id="200-no-assistant"),
        pytest.param(
            info(assistant_supported=True), True, WITH_INFO, id="200-assistant"
        ),
        # An error page has come whole
        pytest.param(
            (HTTPStatus.OK, ContentTypeError(Mock(), ())),
            True,
            WITH_INFO,
            id="200-not-json",
        ),
        pytest.param(HTTPStatus.INTERNAL_SERVER_ERROR, False, WITH_INFO, id="500"),
        # It isn't asked the rest of the update
        pytest.param(
            (HTTPStatus.OK, TimeoutError()),
            False,
            [ALARMS, INFO],
            id="200-body-timed-out",
        ),
        pytest.param(TimeoutError(), False, [ALARMS, INFO], id="timeout"),
    ],
)
def test_available_attribute_when_alarm_check_asks_info(
    clock: Mock, reply: Reply, shown: bool, asked: list[str]
) -> None:
    """Show in the available attribute whether the info asked to check for alarms answered 200.

    That's the update's one info request: the device isn't asked for its info
    again. Each case starts from the other value.
    """
    client, _, network = setup(
        NO_ALARMS | {INFO: TimeoutError() if shown else info(assistant_supported=True)}
    )
    coordinator = Mock(data=poll(client, clock, at(0)))
    sensor = device_sensor(client, coordinator)
    attribute = [sensor.extra_state_attributes["available"]]
    network.asked(SPEAKER)

    network.replies[SPEAKER][INFO] = reply
    poll(client, clock, at(10))
    attribute.append(sensor.extra_state_attributes["available"])

    assert network.asked(SPEAKER) == asked
    assert attribute == [not shown, shown]
    assert sensor.available


@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        pytest.param(info(), True, id="200"),
        pytest.param(HTTPStatus.NOT_FOUND, False, id="404"),
        pytest.param(HTTPStatus.UNAUTHORIZED, False, id="401"),
        pytest.param(HTTPStatus.FOUND, False, id="302"),
        pytest.param((HTTPStatus.OK, TimeoutError()), False, id="200-body-timed-out"),
        pytest.param(TimeoutError(), False, id="timeout"),
    ],
)
def test_available_attribute_of_device_without_alarms(
    clock: Mock, reply: Reply, shown: bool
) -> None:
    """Show in the available attribute whether a device without alarms answers 200 when asked for its info.

    It's true once the check for alarms got its info. Each case then starts from
    the other value.
    """
    client, _, network, chromecast = without_alarms(clock)
    sensor = chromecast["device"]
    assert isinstance(sensor, GoogleHomeDeviceSensor)
    attribute = [sensor.extra_state_attributes["available"]]

    network.replies[SPEAKER][INFO] = TimeoutError() if shown else info()
    poll(client, clock, at(10, 15))
    attribute.append(sensor.extra_state_attributes["available"])
    network.replies[SPEAKER][INFO] = reply
    poll(client, clock, at(10, 30))
    attribute.append(sensor.extra_state_attributes["available"])

    assert network.asked(SPEAKER) == [INFO] * 2
    assert attribute == [True, not shown, shown]
    assert sensor.available


def info_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the messages logged at info level or above."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.INFO
    ]


UNAVAILABLE_MESSAGE = (
    "Device 0 didn't answer 5 updates in a row. Its entities are unavailable until "
    'it answers with something other than "not found".'
)


def test_log_when_unavailable_and_back(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log once when a device's entities become unavailable, and once when they're back.

    "Not found" while it starts doesn't bring them back, so nothing is logged then.
    """
    caplog.set_level(logging.INFO)
    client, _, network = setup(SUPPORTED)
    times = iter(range(at(0), at(10), 15))
    poll(client, clock, next(times))

    for replies in [SILENT] * 7 + [STARTING] + [SUPPORTED] * 2:
        network.replies[SPEAKER] = dict(replies)
        poll(client, clock, next(times))

    assert info_messages(caplog) == [
        UNAVAILABLE_MESSAGE,
        "Device 0 answers again. Its entities are available.",
    ]


def test_log_device_without_alarms_unavailable_and_back(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log that only the device sensor and reboot button of a device without alarms are back."""
    client, _, network, _ = without_alarms(clock)
    caplog.set_level(logging.INFO)
    go_silent(client, clock, network, 7)
    network.replies[SPEAKER][INFO] = info()
    for seconds in (at(12, 0), at(12, 15)):
        poll(client, clock, seconds)

    assert info_messages(caplog) == [
        UNAVAILABLE_MESSAGE,
        (
            "Device 0 answers again. Its device sensor and reboot button are "
            "available; it has no alarms, timers or settings."
        ),
    ]
