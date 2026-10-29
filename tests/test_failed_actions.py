"""Tests for reporting an action that a device didn't carry out, or didn't confirm."""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from json import JSONDecodeError
import logging
from unittest.mock import AsyncMock, MagicMock, Mock

from aiohttp import (
    ClientConnectorError,
    ClientError,
    ClientPayloadError,
    ContentTypeError,
    ServerDisconnectedError,
)
from glocaltokens.client import Device
import pytest

from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.exceptions import (
    AlarmsAndTimersNotFetched,
    DeviceRequestFailed,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    async_reboot_devices,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.exceptions import HomeAssistantError

from .test_missing_devices import ALARM_ID, found, make_client
from .test_offline_devices import press, set_volume, turn_on
from .test_sensor import error_message
from .test_unsupported_devices import (
    ALARMS,
    DND,
    NEW_TOKEN,
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

type Act = Callable[[GoogleHomeBaseEntity], Awaitable[None]]

# Each control, by the label of its entity, which is also what it asks the device
SETTINGS = [
    pytest.param(DND, turn_on, id="do-not-disturb"),
    pytest.param(VOLUME, set_volume, id="alarm-volume"),
]
CONTROLS = [*SETTINGS, pytest.param(REBOOT, press, id="reboot")]


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param(ClientConnectorError(Mock(), OSError()), "offline", id="offline"),
        pytest.param(TimeoutError(), "no_reply", id="timed-out"),
        pytest.param(ServerDisconnectedError(), "no_reply", id="disconnected"),
        pytest.param(HTTPStatus.NOT_FOUND, "not_ready", id="not-found"),
        pytest.param(
            HTTPStatus.INTERNAL_SERVER_ERROR, "request_failed", id="server-error"
        ),
        pytest.param(ClientError(), "request_failed", id="other-error"),
    ],
)
@pytest.mark.parametrize(("control", "act"), CONTROLS)
def test_action_fails_when_device_doesnt_do_it(
    clock: Mock, control: str, act: Act, reply: Reply, reason: str
) -> None:
    """Report an action that the device didn't carry out or confirm, naming it and saying why.

    It's sent once, also right after an update that the device didn't answer, and
    the other entities don't change.
    """
    client, _, network = setup(dict.fromkeys(SUPPORTED, reply))
    coordinator = Mock(data=poll(client, clock, at(0)))
    network.asked(SPEAKER)
    [device] = client.google_devices

    with pytest.raises(DeviceRequestFailed) as err:
        asyncio.run(act(entities(client, coordinator, "device0")[control]))

    assert err.value.reason == reason
    assert device.name in error_message(err.value)
    # The log shows what went wrong
    assert err.value.__cause__ is (reply if isinstance(reply, Exception) else None)
    assert network.asked(SPEAKER) == [control]
    coordinator.async_update_listeners.assert_not_called()


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        pytest.param("ip_address", "offline", id="no-address"),
        pytest.param("auth_token", "request_failed", id="no-token"),
        pytest.param("device", "request_failed", id="not-listed"),
    ],
)
@pytest.mark.parametrize(("control", "act"), CONTROLS)
def test_action_fails_when_it_cant_be_sent(
    control: str, act: Act, missing: str, reason: str
) -> None:
    """Report an action on a device without a known address or token, or that Google no longer lists."""
    client, _, network = setup(SUPPORTED)
    [device] = client.google_devices
    if missing == "device":
        coordinator = Mock(data={})
    else:
        setattr(device, missing, None)
        coordinator = Mock(data={"device0": device})

    with pytest.raises(DeviceRequestFailed) as err:
        asyncio.run(act(entities(client, coordinator, "device0")[control]))

    assert err.value.reason == reason
    assert network.asked(SPEAKER) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(ClientPayloadError("cut off"), id="cut-off"),
        pytest.param(TimeoutError(), id="timed-out"),
        pytest.param(JSONDecodeError("Expecting value", "", 0), id="invalid-json"),
        pytest.param(None, id="empty"),
    ],
)
def test_reboot_asked_once_device_answers_200(
    body: Exception | None, caplog: pytest.LogCaptureFixture
) -> None:
    """Count a reboot as asked for once the device answers 200, whatever comes after.

    A device can go down while it sends the rest of its answer, so the rest isn't
    read, and the request isn't sent again.
    """
    answer = MagicMock(
        status=HTTPStatus.OK,
        json=AsyncMock(side_effect=body)
        if isinstance(body, Exception)
        else AsyncMock(return_value=body),
    )
    response = MagicMock()
    response.__aenter__.return_value = answer
    session = Mock(request=Mock(return_value=response))
    client, _ = make_client(SPEAKER, session=session)
    [device] = client.google_devices
    caplog.set_level(logging.INFO)

    asyncio.run(client.reboot_google_device(device))

    assert session.request.call_count == 1
    answer.json.assert_not_awaited()
    assert device.available
    assert f"Successfully asked {device.name} to reboot." in caplog.messages


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(ClientPayloadError("cut off"), id="cut-off"),
        pytest.param(TimeoutError(), id="timed-out"),
    ],
)
@pytest.mark.parametrize(("control", "act"), SETTINGS)
def test_setting_fails_when_answer_doesnt_arrive(
    control: str, act: Act, body: Exception
) -> None:
    """Report a setting whose answer stops coming after its 200 as one the device may or may not have changed."""
    client, _, network = setup({**SUPPORTED, control: (HTTPStatus.OK, body)})
    coordinator = Mock(data={"device0": client.google_devices[0]})

    with pytest.raises(DeviceRequestFailed) as err:
        asyncio.run(act(entities(client, coordinator, "device0")[control]))

    assert err.value.reason == "no_reply"
    assert network.asked(SPEAKER) == [control]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(None, id="empty"),
        pytest.param(ContentTypeError(Mock(), ()), id="not-json"),
    ],
)
@pytest.mark.parametrize(("control", "act"), SETTINGS)
def test_setting_succeeds_when_answer_doesnt_show_it(
    control: str, act: Act, body: Exception | None
) -> None:
    """Count a 200 that doesn't show the new setting as done, and show the old one until the next update."""
    client, _, _ = setup({**SUPPORTED, control: (HTTPStatus.OK, body)})
    [device] = client.google_devices
    device.set_alarm_volume(70)
    coordinator = Mock(data={"device0": client.google_devices[0]})

    asyncio.run(act(entities(client, coordinator, "device0")[control]))

    assert (device.get_do_not_disturb(), device.get_alarm_volume()) == (False, 70)
    coordinator.async_update_listeners.assert_called_once()


@pytest.mark.parametrize(
    ("retry", "reason", "asked"),
    [
        pytest.param(None, "token_rejected", [REBOOT], id="no-new-token"),
        pytest.param(
            HTTPStatus.UNAUTHORIZED,
            "token_rejected",
            [REBOOT, REBOOT],
            id="new-token-rejected",
        ),
        pytest.param(
            TimeoutError(), "no_reply", [REBOOT, REBOOT], id="retry-timed-out"
        ),
    ],
)
def test_action_fails_with_why_last_try_failed(
    retry: Reply | None, reason: str, asked: list[str]
) -> None:
    """Say why an action failed on the device that rejected its token from what happened last.

    With a new token from Google, the action is sent once more, and that answer
    says why. Without one, it's the rejected token.
    """
    client, glocaltokens, network = setup(
        {**SUPPORTED, REBOOT: HTTPStatus.UNAUTHORIZED}
    )
    [device] = client.google_devices

    def google_answers(**_: object) -> list[Device]:
        assert retry is not None
        network.replies[SPEAKER][REBOOT] = retry
        return [found("device0", SPEAKER, NEW_TOKEN)]

    if retry is not None:
        glocaltokens.get_google_devices.side_effect = google_answers

    with pytest.raises(DeviceRequestFailed) as err:
        asyncio.run(client.reboot_google_device(device))

    assert err.value.reason == reason
    assert network.asked(SPEAKER) == asked


def test_reboot_asked_once_device_answers_200_to_new_token() -> None:
    """Count a reboot as asked for once the device answers 200 to its new token, whatever comes after."""
    client, glocaltokens, network = setup(
        {**SUPPORTED, REBOOT: HTTPStatus.UNAUTHORIZED}
    )
    [device] = client.google_devices

    def google_answers(**_: object) -> list[Device]:
        network.replies[SPEAKER][REBOOT] = (
            HTTPStatus.OK,
            ClientPayloadError("cut off"),
        )
        return [found("device0", SPEAKER, NEW_TOKEN)]

    glocaltokens.get_google_devices.side_effect = google_answers

    asyncio.run(client.reboot_google_device(device))

    assert network.asked(SPEAKER) == [REBOOT, REBOOT]
    assert device.available


@pytest.mark.parametrize(
    ("failing", "translation_key", "placeholders"),
    [
        (["Kitchen"], "device_offline", {"device": "Kitchen"}),
        # In alphabetical order, whatever order Home Assistant passes them in
        (["Office", "Kitchen"], "devices_not_rebooted", {"devices": "Kitchen, Office"}),
    ],
)
def test_reboot_devices_names_every_device_that_failed(
    failing: list[str], translation_key: str, placeholders: dict[str, str]
) -> None:
    """Reboot the devices that answer, then name all that didn't in one error.

    Home Assistant shows one error for an action, however many devices fail. The
    error of one device says why.
    """
    devices = [
        GoogleHomeDevice(name.lower(), name, "token", "192.168.1.10")
        for name in ("Office", "Bedroom", "Kitchen")
    ]

    async def reboot(device: GoogleHomeDevice) -> None:
        if device.name in failing:
            raise DeviceRequestFailed(device.name, "offline")

    coordinator = Mock(data={device.device_id: device for device in devices})
    client = Mock(reboot_google_device=AsyncMock(side_effect=reboot))
    sensors: list[GoogleHomeBaseEntity] = [
        GoogleHomeAlarmsSensor(coordinator, client, d.device_id, d.name, None)
        for d in devices
    ]

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(async_reboot_devices(sensors, Mock()))

    assert [c.args for c in client.reboot_google_device.await_args_list] == [
        (device,) for device in devices
    ]
    assert err.value.translation_key == translation_key
    assert err.value.translation_placeholders == placeholders
    assert all(name in error_message(err.value) for name in failing)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(ClientConnectorError(Mock(), OSError()), id="offline"),
        pytest.param(TimeoutError(), id="timed-out"),
        pytest.param(HTTPStatus.NOT_FOUND, id="not-found"),
        # Google gives the same token again
        pytest.param(HTTPStatus.UNAUTHORIZED, id="token-rejected"),
    ],
)
def test_update_keeps_last_data_when_device_doesnt_answer(
    clock: Mock, reply: Reply, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep a device's last alarms and settings when it doesn't answer an update, and log it only for debugging.

    The update doesn't fail.
    """
    client, _, network = setup(SUPPORTED)
    [device] = poll(client, clock, at(0)).values()
    network.replies[SPEAKER] = dict.fromkeys(SUPPORTED, reply)
    caplog.set_level(logging.DEBUG)

    poll(client, clock, at(3))

    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == [ALARM_ID]
    assert (device.get_do_not_disturb(), device.get_alarm_volume()) == (True, 70)
    assert [r.levelname for r in caplog.records if r.levelno > logging.DEBUG] == []


def test_action_keeps_why_alarms_and_timers_cant_be_fetched() -> None:
    """Keep why an action couldn't get a device's current alarms and timers, for the log."""
    client, _, network = setup({**SUPPORTED, ALARMS: TimeoutError()})
    [device] = client.google_devices

    with pytest.raises(AlarmsAndTimersNotFetched) as err:
        asyncio.run(client.update_alarms_and_timers(device, polling=False))

    assert isinstance(err.value.__cause__, DeviceRequestFailed)
    assert err.value.__cause__.reason == "no_reply"
    assert network.asked(SPEAKER) == [ALARMS]
