"""Tests for replies read through Home Assistant's own session, over TLS, as on an install.

Home Assistant's session decodes JSON with orjson, which rejects some bodies that
Python's json reads, such as NaN, and reads a whole number above 64 bits as a float.
The other tests fake the session, so they don't decode replies at all.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from functools import partial
from http import HTTPStatus
import ipaddress
import json
import logging
from pathlib import Path
import ssl
from unittest.mock import patch

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from ghome_local_api import GoogleHomeLocalClient
from ghome_local_api.const import API_ENDPOINT_ALARM_VOLUME, API_ENDPOINT_ALARMS
import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.models import GoogleHomeDevice

# pylint: disable=wrong-import-order
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .test_sensor import MASTER_TOKEN

JSON = "application/json"
# The volume the last update read, which a reply without one keeps
LAST_VOLUME = 30

# What the speaker answers, by path: its content type and body
type Bodies = dict[str, tuple[str, bytes]]


def certificate(directory: Path) -> ssl.SSLContext:
    """Return a server context with an invented self-signed certificate for 127.0.0.1."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "speaker")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = directory / "cert.pem", directory / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_file, key_file)
    return context


@pytest.fixture(name="speaker")
async def fixture_speaker(
    hass: HomeAssistant,
    tmp_path: Path,
    socket_enabled: None,  # pylint: disable=unused-argument  # loopback only
) -> AsyncIterator[tuple[GlocaltokensApiClient, GoogleHomeDevice, Bodies]]:
    """Serve a speaker at 127.0.0.1 over TLS, and return a client over Home Assistant's session, the device, and its bodies."""
    bodies: Bodies = {}

    async def answer(request: web.Request) -> web.Response:
        content_type, body = bodies[request.path.removeprefix("/")]
        return web.Response(body=body, headers={"Content-Type": content_type})

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", answer)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=certificate(tmp_path))
    await site.start()
    port = runner.addresses[0][1]
    # As the integration makes it: no verification of the device's own certificate
    session = async_create_clientsession(hass, verify_ssl=False)
    with patch(
        "custom_components.google_home.account.GoogleHomeLocalClient",
        partial(GoogleHomeLocalClient, port=port),
    ):
        client = GlocaltokensApiClient(hass, session, master_token=MASTER_TOKEN)
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "127.0.0.1")
    yield client, device, bodies
    await runner.cleanup()


# Bodies that orjson can't decode, though Python's json reads all but the last two
UNDECODABLE = [
    pytest.param(b'{"volume": NaN}', json.JSONDecodeError, id="nan"),
    pytest.param(b'{"volume": Infinity}', json.JSONDecodeError, id="infinity"),
    pytest.param(b'{"volume": 1e999}', json.JSONDecodeError, id="out-of-range"),
    pytest.param(b'{"volume": ', json.JSONDecodeError, id="malformed"),
    pytest.param(b"\xff", UnicodeDecodeError, id="invalid-utf-8"),
]


@pytest.mark.parametrize(("body", "error"), UNDECODABLE)
async def test_undecodable_volume_logged_by_poll_and_raised_by_action(
    speaker: tuple[GlocaltokensApiClient, GoogleHomeDevice, Bodies],
    caplog: pytest.LogCaptureFixture,
    body: bytes,
    error: type[ValueError],
) -> None:
    """Log a volume that can't be decoded at a poll, keeping the last one, and raise the decoder's error for an action.

    Either way the 200 counts as an answer.
    """
    client, device, bodies = speaker
    bodies[API_ENDPOINT_ALARM_VOLUME] = (JSON, body)
    device.alarm_volume, device.available = LAST_VOLUME, False

    await client.update_alarm_volume(device)

    assert device.alarm_volume == LAST_VOLUME
    assert device.available
    assert device.statuses[API_ENDPOINT_ALARM_VOLUME, True] == HTTPStatus.OK
    assert [
        record.getMessage().split(": ")[0]
        for record in caplog.records
        if record.levelno == logging.ERROR
    ] == ["Kitchen sent a reply to setup/assistant/alarms/volume that isn't valid JSON"]

    device.available = False
    with pytest.raises(error):
        await client.set_alarm_volume(device, 50)
    assert device.alarm_volume == LAST_VOLUME
    assert device.available


@pytest.mark.parametrize(
    ("content_type", "body", "volume"),
    [
        pytest.param(JSON, b'{"volume": 0.5}', 50, id="volume"),
        pytest.param(JSON, b"", LAST_VOLUME, id="empty"),
        pytest.param(
            "text/html", b'{"volume": 0.5}', LAST_VOLUME, id="not-json-content-type"
        ),
    ],
)
async def test_volume_reply_that_decodes(
    speaker: tuple[GlocaltokensApiClient, GoogleHomeDevice, Bodies],
    caplog: pytest.LogCaptureFixture,
    content_type: str,
    body: bytes,
    volume: int,
) -> None:
    """Read a volume from a JSON reply; an empty body or another content type has none and isn't a failure."""
    client, device, bodies = speaker
    bodies[API_ENDPOINT_ALARM_VOLUME] = (content_type, body)
    device.alarm_volume = LAST_VOLUME

    await client.update_alarm_volume(device)

    assert device.alarm_volume == volume
    assert not device.update_failed
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_alarm_status_above_64_bits_rejects_reply(
    speaker: tuple[GlocaltokensApiClient, GoogleHomeDevice, Bodies],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject an alarms reply whose status is a whole number above 64 bits: orjson reads it as a float."""
    client, device, bodies = speaker
    alarm = {"id": "alarm/1", "fire_time": 1700000000000, "status": 2**64}
    bodies[API_ENDPOINT_ALARMS] = (
        JSON,
        json.dumps({"alarm": [alarm], "timer": []}).encode(),
    )

    await client.update_alarms_and_timers(device)

    assert device.polled_snapshots == 0
    assert device.get_sorted_alarms() == []
    assert any(
        "API returned unknown json structure" in record.getMessage()
        for record in caplog.records
    )


async def test_reply_in_charset_that_isnt_text_raises_as_it_comes(
    speaker: tuple[GlocaltokensApiClient, GoogleHomeDevice, Bodies],
) -> None:
    """Raise the LookupError of a charset that isn't a text encoding, from a poll and from an action.

    Such a reply isn't counted as an answer that isn't valid JSON: nothing is recorded
    about it, and the device stays as it was.
    """
    client, device, bodies = speaker
    bodies[API_ENDPOINT_ALARM_VOLUME] = (f"{JSON}; charset=base64", b'{"volume": 0.5}')
    device.alarm_volume, device.available = LAST_VOLUME, False

    with pytest.raises(LookupError, match="base64"):
        await client.update_alarm_volume(device)
    with pytest.raises(LookupError, match="base64"):
        await client.set_alarm_volume(device, 50)

    assert device.alarm_volume == LAST_VOLUME
    assert not device.available
    assert device.statuses == {}
