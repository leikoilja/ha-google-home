"""Tests for a speaker's Bluetooth requests, at the session they're sent with.

They check what is sent, and how each answer or failure is returned or raised.
"""

import asyncio
from collections.abc import Awaitable, Callable
from json import JSONDecodeError
from unittest.mock import AsyncMock, MagicMock, Mock

from aiohttp import ClientError, ContentTypeError
import pytest

from custom_components.google_home.bluetooth import (
    BluetoothScanError,
    BluetoothScanUnsupported,
    async_get_bluetooth_scan_results,
    async_start_bluetooth_scan,
)
from custom_components.google_home.models import GoogleHomeDevice


def mock_session(status: int = 200, body: object = None) -> Mock:
    """Return a session whose device answers with this status and JSON body.

    A body that is an exception is what reading it raises.
    """
    response = MagicMock()
    response.__aenter__.return_value = Mock(
        status=status,
        json=AsyncMock(side_effect=body)
        if isinstance(body, BaseException)
        else AsyncMock(return_value=body),
    )
    return Mock(request=Mock(return_value=response))


KITCHEN = GoogleHomeDevice("kitchen", "Kitchen", "token", ip_address="10.0.0.1")


def test_start_scan_request() -> None:
    """Start a 30-second scan that clears the previous results."""
    session = mock_session()

    asyncio.run(async_start_bluetooth_scan(session, KITCHEN))

    method, url = session.request.call_args.args
    assert (method, url) == ("POST", "https://10.0.0.1:8443/setup/bluetooth/scan")
    assert session.request.call_args.kwargs["json"] == {
        "enable": True,
        "clear_results": True,
        "timeout": 30,
    }
    assert (
        session.request.call_args.kwargs["headers"]["cast-local-authorization-token"]
        == "token"
    )
    assert session.request.call_args.kwargs["timeout"].total == 4


def test_scan_results_skip_malformed_entries() -> None:
    """Return the address and signal strength of each well-formed result."""
    session = mock_session(
        body=[
            {"mac_address": "AA:BB:CC:DD:EE:FF", "rssi": -50, "name": ""},
            {"mac_address": "AA:BB:CC:DD:EE:00"},
            "garbage",
        ]
    )

    results = asyncio.run(async_get_bluetooth_scan_results(session, KITCHEN))

    assert results == [{"mac_address": "AA:BB:CC:DD:EE:FF", "rssi": -50}]


INVALID_JSON = JSONDecodeError("Expecting value", "<html>", 0)
# What Python's json raises for an integer of more than 4300 digits
TOO_LONG = ValueError("Exceeds the limit (4300 digits) for integer string conversion")
# What the decoder raises for a charset that isn't a text encoding, such as base64
NOT_TEXT = LookupError("'base64' is not a text encoding")
# What Python's json raises for deep nesting
TOO_DEEP = RecursionError("maximum recursion depth exceeded")


@pytest.mark.parametrize(
    ("status", "body", "error", "message"),
    [
        (404, None, BluetoothScanUnsupported, "Kitchen returned 404"),
        (401, None, BluetoothScanError, "Kitchen returned 401"),
        (500, None, BluetoothScanError, "Kitchen returned 500"),
        (
            200,
            {"error": "no list"},
            BluetoothScanError,
            "Kitchen returned no list of results",
        ),
        (
            200,
            INVALID_JSON,
            BluetoothScanError,
            f"Kitchen didn't answer: {INVALID_JSON!r}",
        ),
        (
            200,
            TimeoutError(),
            BluetoothScanError,
            "Kitchen didn't answer: TimeoutError()",
        ),
        (
            200,
            TOO_LONG,
            BluetoothScanError,
            f"Kitchen didn't answer: {TOO_LONG!r}",
        ),
        (200, NOT_TEXT, LookupError, str(NOT_TEXT)),
        (200, TOO_DEEP, RecursionError, str(TOO_DEEP)),
    ],
)
def test_scan_results_errors(
    status: int, body: object, error: type[Exception], message: str
) -> None:
    """Raise for 404 as unsupported, and for other failures as errors.

    A decoder error other than for a reply that isn't valid JSON is raised as it is.
    """
    session = mock_session(status, body)

    with pytest.raises(error) as raised:
        asyncio.run(async_get_bluetooth_scan_results(session, KITCHEN))
    assert raised.type is error
    assert str(raised.value) == message
    if issubclass(error, BluetoothScanError):
        # A failed answer is chained from the error that caused it, if any
        assert raised.value.__cause__ is (
            body if isinstance(body, BaseException) else None
        )
    else:
        assert raised.value is body


# What aiohttp raises for a header with a control character, such as in a token
FORBIDDEN_HEADER = ValueError(
    "Forbidden control character detected in headers. "
    "Potential header injection attack."
)


@pytest.mark.parametrize(
    "send", [async_start_bluetooth_scan, async_get_bluetooth_scan_results]
)
def test_request_that_cant_be_sent(
    send: Callable[[Mock, GoogleHomeDevice], Awaitable[object]],
) -> None:
    """Raise a request that aiohttp refuses to send as a failed answer.

    Then only that speaker's scan fails, not the whole Bluetooth update.
    """
    session = mock_session()
    session.request.return_value.__aenter__.side_effect = FORBIDDEN_HEADER

    with pytest.raises(BluetoothScanError) as raised:
        asyncio.run(send(session, KITCHEN))
    assert raised.type is BluetoothScanError
    assert str(raised.value) == f"Kitchen didn't answer: {FORBIDDEN_HEADER!r}"
    assert raised.value.__cause__ is FORBIDDEN_HEADER


@pytest.mark.parametrize(
    "send", [async_start_bluetooth_scan, async_get_bluetooth_scan_results]
)
def test_address_that_isnt_an_ip(
    send: Callable[[Mock, GoogleHomeDevice], Awaitable[object]],
) -> None:
    """Raise the address's ValueError before sending anything."""
    session = mock_session()
    device = GoogleHomeDevice("kitchen", "Kitchen", "token", "kitchen.local")

    with pytest.raises(ValueError, match="does not appear to be an IPv4 or IPv6"):
        asyncio.run(send(session, device))
    session.request.assert_not_called()


def test_start_scan_answered_without_json() -> None:
    """Count a scan as started when the device answers 200 with a non-JSON content type."""
    session = mock_session()
    response = session.request.return_value.__aenter__.return_value
    response.json.side_effect = ContentTypeError(Mock(), ())

    # Returning instead of raising is how the scanner knows the scan started
    asyncio.run(async_start_bluetooth_scan(session, KITCHEN))


def test_request_failure_leaves_device_available() -> None:
    """Raise on a connection error without marking the device unavailable."""
    session = mock_session()
    session.request.side_effect = ClientError("offline")
    device = GoogleHomeDevice("kitchen", "Kitchen", "token", ip_address="10.0.0.1")

    with pytest.raises(BluetoothScanError):
        asyncio.run(async_start_bluetooth_scan(session, device))
    assert device.available


def test_read_cancelled_while_results_come() -> None:
    """Raise a read's cancellation as it is, once the answer is released.

    Were it a failed read instead, the scanner would go on to start the next scan.
    """
    session = mock_session()
    answer = session.request.return_value
    # A truthy result would swallow the cancellation
    answer.__aexit__ = AsyncMock(return_value=False)
    body_asked = asyncio.Event()

    async def held_body() -> None:
        body_asked.set()
        await asyncio.Event().wait()

    answer.__aenter__.return_value.json.side_effect = held_body

    async def read_then_cancel() -> None:
        read = asyncio.create_task(async_get_bluetooth_scan_results(session, KITCHEN))
        await body_asked.wait()
        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await read

    asyncio.run(read_then_cancel())
    answer.__aexit__.assert_awaited_once()
    assert answer.__aexit__.await_args.args[0] is asyncio.CancelledError
