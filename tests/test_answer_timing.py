"""Tests for when a device's answer takes effect: as soon as its status comes.

A 200's status removes the device's token wait, and a reboot's makes the device
available, before its body is read or the answer is released. A request cancelled
while either is pending keeps those effects, and another request meanwhile sees them.
"""

import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, Mock

from ghome_local_api.const import API_ENDPOINT_ALARMS, API_ENDPOINT_REBOOT
import pytest

from custom_components.google_home.account import TokenWait
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.exceptions import DeviceRequestFailed
from custom_components.google_home.models import GoogleHomeDevice

from .test_missing_devices import make_client


def answer_context(answer: MagicMock, *, release: AsyncMock | None = None) -> MagicMock:
    """Return the session's context for an answer, released with release if given."""
    context = MagicMock()
    context.__aenter__.return_value = answer
    # A truthy result would swallow an exception raised in the context
    context.__aexit__ = release or AsyncMock(return_value=False)
    return context


def held(started: asyncio.Event, result: object = None) -> AsyncMock:
    """Return a coroutine mock that sets started, then waits until cancelled."""

    async def hold(*_: object) -> object:
        started.set()
        await asyncio.Event().wait()
        return result

    return AsyncMock(side_effect=hold)


def waiting_device(
    session: Mock,
) -> tuple[GlocaltokensApiClient, Mock, GoogleHomeDevice]:
    """Return a client, its fake glocaltokens, and its device, which waits before its rejection fetches Google's list."""
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [device] = client.google_devices
    # It rejected the token from the fetch at 0, so waits until a minute after it
    wait = TokenWait()
    wait.fetch_started(0.0)
    client._token_waits[device.device_id] = wait  # noqa: SLF001  # pylint: disable=protected-access
    return client, glocaltokens, device


def token_waits(client: GlocaltokensApiClient) -> dict[str, TokenWait]:
    """Return the token waits of the client's devices."""
    return client._token_waits  # noqa: SLF001  # pylint: disable=protected-access


@pytest.mark.usefixtures("clock")
def test_poll_cancelled_while_body_comes_keeps_wait_removed() -> None:
    """Keep the token wait removed once a 200 came, though the poll is cancelled before its body.

    The 200 isn't recorded as the alarms' status: its body never came.
    """
    body_asked = asyncio.Event()
    answer = MagicMock(status=HTTPStatus.OK, json=held(body_asked))
    session = Mock(request=Mock(return_value=answer_context(answer)))
    client, _, device = waiting_device(session)

    async def poll_then_cancel() -> None:
        poll = asyncio.create_task(client.update_alarms_and_timers(device))
        await body_asked.wait()
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll

    asyncio.run(poll_then_cancel())

    assert device.device_id not in token_waits(client)
    assert (API_ENDPOINT_ALARMS, True) not in device.statuses


@pytest.mark.usefixtures("clock")
def test_rejection_while_poll_body_comes_fetches_google_list() -> None:
    """Fetch Google's list for an action whose token is rejected while a poll's 200 body is still coming.

    The poll's 200 ended the device's wait, so the action doesn't wait for its body.
    """
    body_asked, body_sent = asyncio.Event(), asyncio.Event()

    async def alarms_body() -> object:
        body_asked.set()
        await body_sent.wait()
        return {"alarm": [], "timer": []}

    def request(_method: str, url: str, **_: object) -> MagicMock:
        if url.endswith(API_ENDPOINT_ALARMS):
            answer = MagicMock(
                status=HTTPStatus.OK, json=AsyncMock(side_effect=alarms_body)
            )
        else:
            answer = MagicMock(status=HTTPStatus.UNAUTHORIZED)
        return answer_context(answer)

    client, glocaltokens, device = waiting_device(
        Mock(request=Mock(side_effect=request))
    )

    async def act_while_poll_body_comes() -> int:
        poll = asyncio.create_task(client.update_alarms_and_timers(device))
        await body_asked.wait()
        with pytest.raises(DeviceRequestFailed):
            await client.set_do_not_disturb(device, True)
        fetched = int(glocaltokens.get_google_devices.call_count)
        body_sent.set()
        await poll
        return fetched

    assert asyncio.run(act_while_poll_body_comes()) == 1


@pytest.mark.usefixtures("clock")
def test_reboot_cancelled_while_released_keeps_device_available() -> None:
    """Keep a device available once its reboot's 200 came, though the action is cancelled while the answer is released.

    The token wait stays removed, and no reboot status is recorded.
    """
    releasing = asyncio.Event()
    session = Mock(
        request=Mock(
            return_value=answer_context(
                MagicMock(status=HTTPStatus.OK), release=held(releasing, False)
            )
        )
    )
    client, _, device = waiting_device(session)
    device.available = False

    async def reboot_then_cancel() -> None:
        reboot = asyncio.create_task(client.reboot_google_device(device))
        await releasing.wait()
        reboot.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reboot

    asyncio.run(reboot_then_cancel())

    assert device.available
    assert device.device_id not in token_waits(client)
    assert (API_ENDPOINT_REBOOT, False) not in device.statuses
