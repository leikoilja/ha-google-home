"""Tests for updates and actions when a device doesn't answer."""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from unittest.mock import Mock

from aiohttp import ClientConnectorError, ClientTimeout
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
    NEW_TOKEN,
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


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError(), id="timeout"),
        pytest.param(ClientConnectorError(Mock(), OSError()), id="offline"),
    ],
)
@pytest.mark.parametrize(
    ("unanswered", "asked"),
    [
        pytest.param(ALARMS, [ALARMS], id="alarms"),
        pytest.param(VOLUME, [ALARMS, VOLUME], id="alarm-volume"),
    ],
)
def test_update_stops_asking_device_that_doesnt_answer(
    clock: Mock, error: Exception, unanswered: str, asked: list[str]
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


def test_update_stops_asking_device_when_retry_doesnt_answer(clock: Mock) -> None:
    """Ask a device nothing more in an update when it doesn't answer with its new token either.

    It rejected its token, and Google gave it a new one in the same update.
    """
    client, glocaltokens, network = setup(
        {**SUPPORTED, ALARMS: HTTPStatus.UNAUTHORIZED}
    )

    def google_answers(**_: object) -> list[Device]:
        network.replies[SPEAKER][ALARMS] = TimeoutError()
        return [found("device0", SPEAKER, NEW_TOKEN)]

    glocaltokens.get_google_devices.side_effect = google_answers
    poll(client, clock, at(0))

    assert network.asked(SPEAKER) == [ALARMS, ALARMS]
    assert client.google_devices[0].auth_token == NEW_TOKEN


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
