"""Tests for getting a new token from Google when a device rejects its token."""

import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from unittest.mock import ANY, AsyncMock, MagicMock, Mock

from aiohttp import ClientConnectorError
from glocaltokens.client import Device
import pytest

from custom_components.google_home import async_update_devices
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    FETCH_DEVICES_INTERVAL,
    HEADER_CAST_LOCAL_AUTH,
)
from custom_components.google_home.exceptions import AlarmsAndTimersNotDeleted
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import GoogleHomeAlarmsSensor
from custom_components.google_home.types import JsonDict

from .test_missing_devices import (
    ALARM_ID,
    FETCH_ERRORS,
    HASS,
    LOCAL_AUTH_TOKEN,
    MINUTE,
    UNREACHABLE,
    can_delete,
    fetches_in,
    found,
    make_client,
    rejected,
    until,
)

# make_client gives each device this token, and Google then gives LOCAL_AUTH_TOKEN
OLD_TOKEN = "token"
# A token that a device gets after the one Google gave first
NEWER_TOKEN = "y" * 108
# What a device answers to any request it accepts
REPLY = {
    "alarm": [{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}],
    "timer": [],
    "volume": 0.7,
    "notifications_enabled": False,
    "success": True,
}


def accepting(
    token: str, before_answer: Callable[[str], Awaitable[None]] | None = None
) -> Mock:
    """Return a session to which every device answers REPLY with this token, and 401 to any other.

    If given, before_answer is awaited with the token sent before the device answers.
    """

    def request(
        _method: str, _url: str, *, headers: dict[str, str], **_: object
    ) -> MagicMock:
        sent = headers[HEADER_CAST_LOCAL_AUTH]
        answer = MagicMock(
            status=HTTPStatus.OK if sent == token else HTTPStatus.UNAUTHORIZED,
            json=AsyncMock(return_value=REPLY),
        )

        async def enter() -> MagicMock:
            if before_answer is not None:
                await before_answer(sent)
            return answer

        response = MagicMock()
        response.__aenter__.side_effect = enter
        return response

    return Mock(request=Mock(side_effect=request))


def tokens_sent(
    session: Mock, *, to: str | None = None, data: object = ANY
) -> list[str]:
    """Return the token of each request sent, in order: if given, only those to this address or with this body.

    Requests while polling have no body.
    """
    return [
        request.kwargs["headers"][HEADER_CAST_LOCAL_AUTH]
        for request in session.request.call_args_list
        if (to is None or f"//{to}:" in request.args[1])
        and request.kwargs["json"] == data
    ]


def test_update_with_new_token_after_token_rejected() -> None:
    """Update a device that rejects its token in the same update, with the new token Google gives.

    A device's token changes when it restarts. Otherwise it would show as
    unavailable, and its alarms, timers and settings wouldn't update, until the
    next update.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices

    asyncio.run(client.update_google_devices_information())

    assert glocaltokens.get_google_devices.call_count == 1
    # The rejected request is sent again, and the next two use the new token
    assert tokens_sent(session) == [OLD_TOKEN] + [LOCAL_AUTH_TOKEN] * 3
    assert kitchen.available
    assert client.google_devices_fetched
    assert [alarm.alarm_id for alarm in kitchen.get_sorted_alarms()] == [ALARM_ID]
    assert kitchen.get_do_not_disturb()
    assert kitchen.get_alarm_volume() == 70


def test_one_fetch_when_devices_reject_their_tokens_together() -> None:
    """Fetch Google's list once when two devices reject their tokens at the same time, and update both.

    The second device waits for the fetch that the first one started, rather
    than fetch the list again or give up.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client(
        "10.0.0.2",
        "10.0.0.3",
        session=session,
        # Google answers once both devices have rejected their tokens
        google_answers_when=lambda: session.request.call_count >= 2,
    )

    asyncio.run(client.update_google_devices_information())

    assert glocaltokens.get_google_devices.call_count == 1
    for device in client.google_devices:
        assert device.available
        assert tokens_sent(session, to=device.ip_address) == (
            [OLD_TOKEN] + [LOCAL_AUTH_TOKEN] * 3
        )


@pytest.mark.parametrize(
    "google",
    [
        pytest.param(OLD_TOKEN, id="same-token"),
        pytest.param(LOCAL_AUTH_TOKEN, id="new-token-rejected"),
        *FETCH_ERRORS,
        UNREACHABLE,
    ],
)
def test_no_usable_token_after_token_rejected(
    clock: Mock, google: str | Exception
) -> None:
    """Fetch Google's list only once in an update when the devices that reject their tokens get none they accept.

    However long the fetch takes. The devices keep their data, and the next
    update fetches the list again.
    """
    session = accepting(NEWER_TOKEN)
    client, glocaltokens = make_client(
        "10.0.0.2",
        "10.0.0.3",
        session=session,
        google_answers_when=lambda: session.request.call_count >= 2,
    )
    kitchen, bedroom = client.google_devices
    kitchen.set_alarms([{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}])
    kitchen.set_alarm_volume(70)

    def google_answers(**_: object) -> list[Device]:
        # Google takes 5 minutes to answer
        clock.return_value += 5 * MINUTE
        if isinstance(google, Exception):
            raise google
        return [
            found(device.device_id, device.ip_address, token=google)
            for device in (kitchen, bedroom)
        ]

    glocaltokens.get_google_devices.side_effect = google_answers

    assert asyncio.run(client.update_google_devices_information()) == [
        kitchen,
        bedroom,
    ]

    assert glocaltokens.get_google_devices.call_count == 1
    assert (kitchen.available, bedroom.available) == (False, False)
    assert [alarm.alarm_id for alarm in kitchen.get_sorted_alarms()] == [ALARM_ID]
    assert kitchen.get_alarm_volume() == 70
    assert not can_delete(client, [kitchen, bedroom], "removed")

    # Google gives tokens they accept by the next update
    glocaltokens.get_google_devices.side_effect = None
    glocaltokens.get_google_devices.return_value = [
        found(device.device_id, device.ip_address, token=NEWER_TOKEN)
        for device in (kitchen, bedroom)
    ]
    asyncio.run(client.update_google_devices_information())

    assert glocaltokens.get_google_devices.call_count == 2
    assert (kitchen.available, bedroom.available) == (True, True)


def test_action_during_scheduled_fetch(clock: Mock) -> None:
    """Send an action again with the new token that the fetch already running brings.

    The action waits for the update's fetch rather than fetch the list again or
    ask to try again later.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client(
        "10.0.0.2",
        session=session,
        # Google answers once the action has been rejected
        google_answers_when=lambda: session.request.call_count >= 1,
    )
    [kitchen] = client.google_devices
    clock.return_value = FETCH_DEVICES_INTERVAL

    async def run() -> None:
        update_task = asyncio.create_task(client.update_google_devices_information())
        # The scheduled fetch has started, and waits for Google
        await until(lambda: client.next_scheduled_fetch == 2 * FETCH_DEVICES_INTERVAL)
        await client.update_do_not_disturb(kitchen, enable=True)
        await update_task

    asyncio.run(run())

    assert glocaltokens.get_google_devices.call_count == 1
    assert tokens_sent(session, data={"notifications_enabled": False}) == [
        OLD_TOKEN,
        LOCAL_AUTH_TOKEN,
    ]
    assert tokens_sent(session, data=None) == [LOCAL_AUTH_TOKEN] * 3
    assert kitchen.available


def test_update_during_action_fetch() -> None:
    """Use the fetch that an action started for an update that starts meanwhile, rather than fetch again.

    The list is unknown, so the update would otherwise fetch it at its start.
    """
    google_answers = asyncio.Event()
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client(
        "10.0.0.2", session=session, google_answers_when=google_answers.is_set
    )
    client.google_devices_fetched = False
    [kitchen] = client.google_devices

    async def run() -> None:
        action = asyncio.create_task(client.update_do_not_disturb(kitchen, enable=True))
        # The action has been rejected and its fetch waits for Google
        await until(lambda: session.request.call_count == 1)
        update_task = asyncio.create_task(client.update_google_devices_information())
        # A new task starts on the next turn of the event loop, and the update
        # runs until it waits for the action's fetch
        await asyncio.sleep(0)
        google_answers.set()
        await asyncio.gather(action, update_task)

    asyncio.run(run())

    assert glocaltokens.get_google_devices.call_count == 1
    assert tokens_sent(session, data={"notifications_enabled": False}) == [
        OLD_TOKEN,
        LOCAL_AUTH_TOKEN,
    ]
    assert tokens_sent(session, data=None) == [LOCAL_AUTH_TOKEN] * 3
    assert kitchen.available
    assert client.google_devices_fetched


def test_fetch_once_in_update_after_action_rejects_new_token(clock: Mock) -> None:
    """Don't fetch Google's list again in an update that fetched it, when an action meanwhile finds the new token rejected.

    The scheduled fetch gives the new token and then looks for a device at a
    known host. Meanwhile an action, sent with the old token, gets rejected,
    and its retry with the new token is rejected too, so the list becomes
    unknown. The update has already used its fetch, so the next update gets the
    token the device accepts.
    """

    async def until_new_token(token: str) -> None:
        # The action, sent with the old token, is answered once the fetch has
        # given the new one
        if token == OLD_TOKEN:
            await until(lambda: kitchen.auth_token == LOCAL_AUTH_TOKEN)

    session = accepting(NEWER_TOKEN, before_answer=until_new_token)
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices
    client.known_hosts = ["10.0.0.9"]

    async def known_host_answers() -> MagicMock:
        # Once the action has sent its request again with the new token
        await until(lambda: session.request.call_count >= 2)
        return MagicMock(json=AsyncMock(return_value={}))

    known_host = MagicMock()
    known_host.__aenter__.side_effect = known_host_answers
    session.get = Mock(return_value=known_host)
    # A device without an address makes the fetch look for it at the known host
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2"),
        found("den", None),
    ]
    clock.return_value = FETCH_DEVICES_INTERVAL

    async def run() -> None:
        action = asyncio.create_task(client.update_do_not_disturb(kitchen, enable=True))
        # The action has sent its request before the update starts
        await until(lambda: session.request.call_count == 1)
        await client.update_google_devices_information()
        await action

    asyncio.run(run())

    assert glocaltokens.get_google_devices.call_count == 1
    assert tokens_sent(session, data={"notifications_enabled": False}) == [
        OLD_TOKEN,
        LOCAL_AUTH_TOKEN,
    ]
    assert (kitchen.available, client.google_devices_fetched) == (False, False)

    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", token=NEWER_TOKEN),
        found("den", None),
    ]
    clock.return_value = FETCH_DEVICES_INTERVAL + 3 * MINUTE
    asyncio.run(client.update_google_devices_information())

    assert glocaltokens.get_google_devices.call_count == 2
    assert (kitchen.available, client.google_devices_fetched) == (True, True)


def test_ask_to_sign_in_when_token_fetch_rejected() -> None:
    """Ask to sign in again in the update in which a device's rejected token makes Google reject the master token."""
    client, glocaltokens = make_client("10.0.0.2", session=accepting(LOCAL_AUTH_TOKEN))
    glocaltokens.get_google_devices.side_effect = rejected()
    entry = Mock()

    assert asyncio.run(async_update_devices(HASS, entry, client)) == (
        client.google_devices
    )

    assert glocaltokens.get_google_devices.call_count == 1
    entry.async_start_reauth.assert_called_once_with(HASS)


def test_token_fetch_postpones_scheduled_fetch(clock: Mock) -> None:
    """Fetch Google's list on schedule 20 minutes after a fetch for a rejected token, not 20 minutes after the one before.

    The 20 minutes are written out, not taken from the constant.
    """
    client, glocaltokens = make_client("10.0.0.2", session=accepting(LOCAL_AUTH_TOKEN))
    clock.return_value = 10 * MINUTE
    asyncio.run(client.update_google_devices_information())
    assert glocaltokens.get_google_devices.call_count == 1

    # When the fetch at setup would have been due
    clock.return_value = 20 * MINUTE
    assert fetches_in(client, glocaltokens, 1) == 1
    clock.return_value = 30 * MINUTE - 1
    assert fetches_in(client, glocaltokens, 1) == 1
    clock.return_value = 30 * MINUTE
    assert fetches_in(client, glocaltokens, 1) == 2


# Each action, its request's body, and what the device shows afterwards: Do Not
# Disturb, alarm volume and alarms
ACTIONS = [
    pytest.param(
        lambda client, device: client.update_do_not_disturb(device, enable=True),
        {"notifications_enabled": False},
        (True, 70, [ALARM_ID]),
        id="do-not-disturb",
    ),
    pytest.param(
        lambda client, device: client.update_alarm_volume(device, volume=40),
        {"volume": 0.4},
        (False, 40, [ALARM_ID]),
        id="alarm-volume",
    ),
    pytest.param(
        lambda client, device: client.reboot_google_device(device),
        {"params": "now"},
        (False, 70, [ALARM_ID]),
        id="reboot",
    ),
    pytest.param(
        lambda client, device: client.delete_alarm_or_timer(device, [ALARM_ID]),
        {"ids": [ALARM_ID]},
        (False, 70, []),
        id="delete",
    ),
]


@pytest.mark.parametrize(("action", "data", "shown"), ACTIONS)
def test_action_after_token_rejected(
    action: Callable[[GlocaltokensApiClient, GoogleHomeDevice], Awaitable[object]],
    data: JsonDict,
    shown: tuple[bool, int, list[str]],
) -> None:
    """Carry out an action on a device that rejects its token, with the new token Google gives.

    Rather than ask the user to try again later.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices
    kitchen.set_alarms([{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}])
    kitchen.set_alarm_volume(70)

    asyncio.run(action(client, kitchen))

    assert glocaltokens.get_google_devices.call_count == 1
    # The same request, sent again with the new token
    assert tokens_sent(session) == [OLD_TOKEN, LOCAL_AUTH_TOKEN]
    assert tokens_sent(session, data=data) == [OLD_TOKEN, LOCAL_AUTH_TOKEN]
    assert kitchen.available
    assert (
        kitchen.get_do_not_disturb(),
        kitchen.get_alarm_volume(),
        [alarm.alarm_id for alarm in kitchen.get_sorted_alarms()],
    ) == shown


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError(), id="timed-out"),
        pytest.param(ClientConnectorError(Mock(), OSError()), id="connection-error"),
    ],
)
def test_action_not_sent_again_when_device_doesnt_answer(error: Exception) -> None:
    """Send an action once when the device doesn't answer, as it may have carried it out.

    Only a rejected token makes the request go out again.
    """
    session = Mock(request=Mock(side_effect=error))
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices

    asyncio.run(client.reboot_google_device(kitchen))

    assert session.request.call_count == 1
    assert glocaltokens.get_google_devices.call_count == 0
    assert not kitchen.available


def test_delete_all_after_token_rejected() -> None:
    """Delete all alarms from a device that rejects its token, with the new token Google gives.

    The current alarms are fetched again with it, and then deleted once.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices
    sensor = GoogleHomeAlarmsSensor(
        Mock(data=client.google_devices), client, "device0", "device0", None
    )

    assert asyncio.run(sensor.async_delete_all(Mock()))

    assert glocaltokens.get_google_devices.call_count == 1
    assert tokens_sent(session, data=None) == [OLD_TOKEN, LOCAL_AUTH_TOKEN]
    assert tokens_sent(session, data={"ids": [ALARM_ID]}) == [LOCAL_AUTH_TOKEN]
    assert kitchen.get_sorted_alarms() == []


def test_delete_fails_when_new_token_rejected() -> None:
    """Report a delete that the device rejects with its old token and with the new one Google gives.

    It keeps the alarm, which the device may still have.
    """
    session = accepting(NEWER_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices
    kitchen.set_alarms([{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}])

    with pytest.raises(AlarmsAndTimersNotDeleted) as err:
        asyncio.run(client.delete_alarm_or_timer(kitchen, [ALARM_ID]))

    assert err.value.device_name == kitchen.name
    assert glocaltokens.get_google_devices.call_count == 1
    assert tokens_sent(session, data={"ids": [ALARM_ID]}) == [
        OLD_TOKEN,
        LOCAL_AUTH_TOKEN,
    ]
    assert [alarm.alarm_id for alarm in kitchen.get_sorted_alarms()] == [ALARM_ID]
