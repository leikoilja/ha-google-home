"""Tests for updates and actions when a device doesn't answer."""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from unittest.mock import Mock

from aiohttp import ClientConnectorError, ClientPayloadError, ClientTimeout
from glocaltokens.client import Device
import pytest

from custom_components.google_home.button import RebootButton
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber
from custom_components.google_home.switch import DoNotDisturbSwitch

from .test_missing_devices import found
from .test_unsupported_devices import (
    ALARMS,
    DND,
    EVERYTHING,
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
    entities,
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
