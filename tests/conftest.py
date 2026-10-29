"""Fixtures shared by the tests."""

from collections.abc import Iterator
import re
from unittest.mock import MagicMock, Mock, patch

from glocaltokens.client import Device
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from syrupy.assertion import SnapshotAssertion
from yarl import URL

from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.core import HomeAssistant

from .test_missing_devices import MASTER_TOKEN, found
from .test_unsupported_devices import ENDPOINTS, SPEAKER, SUPPORTED, Reply

# pylint: enable=wrong-import-order

# The speaker that the fake Google lists, at SPEAKER
SPEAKER_ID = "kitchen"
SPEAKER_CLOUD_ID = "kitchen-cloud-id"
SPEAKER_NAME = "Kitchen speaker"
DELETE = "delete"


def kitchen_speaker(ip_address: str | None = SPEAKER) -> Device:
    """Return the speaker as glocaltokens returns it, with the address mDNS found."""
    return found(
        SPEAKER_ID, ip_address, name=SPEAKER_NAME, cloud_device_id=SPEAKER_CLOUD_ID
    )


@pytest.fixture(name="clock")
def fixture_clock() -> Iterator[Mock]:
    """Set the time the client reads, in seconds since setup fetched Google's list."""
    with (
        patch(
            "custom_components.google_home.api.monotonic", return_value=0.0
        ) as monotonic,
        patch("custom_components.google_home.account.monotonic", monotonic),
        patch("custom_components.google_home.mdns.monotonic", monotonic),
    ):
        yield monotonic


@pytest.fixture(name="snapshot")
def fixture_snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Compare with snapshots as Home Assistant does, leaving out generated IDs and times.

    The plugin's fixture that does this loses to syrupy's own.
    """
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(name="config_entry")
def fixture_config_entry(
    hass: HomeAssistant,
    enable_custom_integrations: None,  # pylint: disable=unused-argument
) -> MockConfigEntry:
    """Return an entry of this integration, as signing in with a master token saves it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="test@example.com",
        data={
            CONF_MASTER_TOKEN: MASTER_TOKEN,
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "",
            CONF_ANDROID_ID: "android-id",
        },
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(name="google")
def fixture_google(
    mock_async_zeroconf: MagicMock,  # pylint: disable=unused-argument
) -> Iterator[Mock]:
    """Fake glocaltokens' fetch of Google's device list, which lists one speaker.

    mDNS finds no other device.
    """
    with (
        # With autospec, a call that glocaltokens wouldn't accept fails
        patch(
            "glocaltokens.client.GLocalAuthenticationTokens.get_google_devices",
            autospec=True,
            return_value=[kitchen_speaker()],
        ) as google,
        patch("custom_components.google_home.mdns.AsyncServiceBrowser"),
    ):
        yield google


@pytest.fixture(name="replies")
def fixture_replies(
    aioclient_mock: AiohttpClientMocker,
) -> dict[str, dict[str, Reply]]:
    """Answer each request to a speaker as this table says when it's sent.

    By address and endpoint, as in test_unsupported_devices. The speaker at SPEAKER
    is a Google or Nest speaker.
    """
    replies: dict[str, dict[str, Reply]] = {SPEAKER: dict(SUPPORTED)}
    endpoints = {**ENDPOINTS, API_ENDPOINT_ALARM_DELETE: DELETE}

    async def answer(method: str, url: URL, _data: object) -> AiohttpClientMockResponse:
        reply = replies[str(url.host)][endpoints[url.path_qs.removeprefix("/")]]
        if isinstance(reply, Exception):
            return AiohttpClientMockResponse(method, url, exc=reply)
        status, body = reply if isinstance(reply, tuple) else (reply, None)
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    for method in ("get", "post"):
        aioclient_mock.request(method, re.compile(""), side_effect=answer)
    return replies
