"""Fixtures shared by the tests."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager
import copy
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
import re
from typing import Concatenate, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from weakref import WeakKeyDictionary

from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module
from glocaltokens.client import Device, GLocalAuthenticationTokens
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.google_home.account import GoogleAccountClient
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    HEADER_CAST_LOCAL_AUTH,
)
from custom_components.google_home.mdns import FoundDevices

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components.repairs import RepairsFlowContext, RepairsFlowManager
from homeassistant.config_entries import (
    ConfigEntriesFlowManager,
    ConfigSubentryFlowManager,
    OptionsFlowManager,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowManager, FlowResult, FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.translation import async_get_translations
from script.check_translations import placeholders

from .test_missing_devices import MASTER_TOKEN, found
from .test_unsupported_devices import ENDPOINTS, SPEAKER, SUPPORTED, Reply

# pylint: enable=wrong-import-order

# The speaker that the fake Google lists, at SPEAKER
SPEAKER_ID = "kitchen"
SPEAKER_CLOUD_ID = "kitchen-cloud-id"
SPEAKER_NAME = "Kitchen speaker"
# A second speaker, which the two_speakers fixture lists after the kitchen's
BEDROOM = "10.0.0.3"
BEDROOM_ID = "bedroom"
DELETE = "delete"


def kitchen_speaker(ip_address: str | None = SPEAKER) -> Device:
    """Return the speaker as glocaltokens returns it, with the address mDNS found."""
    return found(
        SPEAKER_ID, ip_address, name=SPEAKER_NAME, cloud_device_id=SPEAKER_CLOUD_ID
    )


def bedroom_speaker(ip_address: str | None = BEDROOM) -> Device:
    """Return the second speaker as glocaltokens returns it."""
    return found(BEDROOM_ID, ip_address, name="Bedroom speaker")


@dataclass
class Held:
    """A reply in the replies table that the speaker sends only once released."""

    reply: Reply
    asked: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class ForToken:
    """A reply in the replies table to requests with this token.

    Requests with another token are rejected, as by a speaker whose token changed.
    """

    token: str
    reply: Reply


# What each speaker answers, by address and endpoint
type Replies = dict[str, dict[str, Reply | Held | ForToken]]


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


@pytest.fixture(name="mdns_cache", autouse=True)
def fixture_mdns_cache() -> Iterator[dict[str, tuple[str, str]]]:
    """Fake the Cast devices in mDNS's cache, by Google's other ID, with name and address.

    After each fetch that works, the browser starts again and replays the cache.
    Tests also list a device with the address that mDNS has cached for it, as
    glocaltokens returned it while it scanned at each fetch. With discovery off it
    doesn't, so Google's list comes without addresses: this strips them and replays
    them with the cache. Tests of the browser itself list devices without addresses.
    """
    cache: dict[str, tuple[str, str]] = {}
    listed: WeakKeyDictionary[FoundDevices, list[tuple[str, str, str]]] = (
        WeakKeyDictionary()
    )
    use_google_devices = GoogleAccountClient._use_google_devices  # noqa: SLF001  # pylint: disable=protected-access
    browse_again = FoundDevices.async_browse_again

    def use(
        client: GoogleAccountClient, devices: list[Device], home_graph: HomeGraph
    ) -> None:
        # mDNS reports Google's other ID in lower case
        listed[client.found_devices] = [
            (device.cloud_device_id.lower(), device.device_name, device.ip_address)
            for device in devices
            if device.cloud_device_id and device.ip_address
        ]
        unaddressed = []
        for device in devices:
            device = copy.copy(device)
            device.network_device = device.ip_address = device.port = None
            unaddressed.append(device)
        use_google_devices(client, unaddressed, home_graph)

    async def replay(found_devices: FoundDevices) -> None:
        await browse_again(found_devices)
        cached = [(key, *value) for key, value in cache.items()]
        for cloud_device_id, name, address in cached + listed.get(found_devices, []):
            found_devices.async_device_found(
                cloud_device_id, name, address, replayed=True
            )

    with (
        patch.object(GoogleAccountClient, "_use_google_devices", use),
        patch.object(FoundDevices, "async_browse_again", replay),
    ):
        yield cache


def no_browser() -> AbstractContextManager[Mock]:
    """Replace mDNS's browser with one that reports nothing and can be cancelled."""
    return patch(
        "custom_components.google_home.mdns.AsyncServiceBrowser",
        side_effect=lambda *_args, **_kwargs: Mock(async_cancel=AsyncMock()),
    )


@pytest.fixture(name="no_setup_wait", autouse=True)
def fixture_no_setup_wait() -> Iterator[None]:
    """Don't make setup wait for mDNS in real time; tests of the wait set their own."""
    with patch("custom_components.google_home.mdns.CAST_SETUP_WAIT", 0):
        yield


@dataclass
class Timer:
    """A timer that the client set, as Home Assistant's async_call_later would."""

    at: float
    action: Callable[[datetime], None]
    cancelled: bool = False
    fired: bool = False

    def cancel(self) -> None:
        """Cancel the timer."""
        self.cancelled = True


@pytest.fixture(name="timers")
def fixture_timers(clock: Mock) -> Iterator[list[Timer]]:
    """Record the timers the client sets, at the client's clock."""
    timers: list[Timer] = []

    def call_later(
        _hass: object, delay: float, action: Callable[[datetime], None]
    ) -> Callable[[], None]:
        timer = Timer(float(clock.return_value) + delay, action)
        timers.append(timer)
        return timer.cancel

    with patch(
        "custom_components.google_home.mdns.async_call_later", side_effect=call_later
    ):
        yield timers


async def assert_flow_text(
    manager: FlowManager, result: FlowResult, issue_id: str | None = None
) -> None:
    """Check that the flow's step, menu options, errors and abort reason have English text.

    Home Assistant looks the text up under the result's translation domain, which it
    sets to its own for its reasons, such as single_instance_allowed and
    reauth_successful.

    The frontend fills the placeholders in these texts, and in the step's other
    texts, from the result's description placeholders. It shows an error instead of
    a text whose placeholder has no value. A menu's title and a form's submit button
    get no values, so they can't have placeholders.

    The fix of a repair has its texts under the repair's issue ID, or translation key
    while it has one.
    """
    domain = result.get("translation_domain") or DOMAIN
    if isinstance(manager, RepairsFlowManager):
        # A finished fix removes the repair
        issue = ir.async_get(manager.hass).async_get_issue(domain, cast(str, issue_id))
        key = issue.translation_key if issue and issue.translation_key else issue_id
        category = "issues"
        prefix = f"component.{domain}.issues.{key}.fix_flow"
    # The manager's type parameters differ, so check it as an object
    elif isinstance(cast(object, manager), ConfigSubentryFlowManager):
        # The handler is the entry's ID and the subentry type
        category = "config_subentries"
        prefix = f"component.{domain}.{category}.{result['handler'][1]}"
    else:
        category = "options" if isinstance(manager, OptionsFlowManager) else "config"
        prefix = f"component.{domain}.{category}"
    text = await async_get_translations(manager.hass, "en", category, [domain])
    keys = [
        f"{prefix}.error.{error}" for error in (result.get("errors") or {}).values()
    ]
    if result["type"] is FlowResultType.ABORT:
        keys.append(f"{prefix}.abort.{result['reason']}")
    if result["type"] in {FlowResultType.FORM, FlowResultType.MENU}:
        step = f"{prefix}.step.{result['step_id']}"
        assert any(key.startswith(f"{step}.") for key in text), f"No text: {step}"
        keys += [
            f"{step}.menu_options.{option}"
            for option in cast(list[str], result.get("menu_options", []))
        ]
        keys += [key for key in text if key.startswith(f"{step}.")]
        valueless = (
            f"{step}.title"
            if result["type"] is FlowResultType.MENU
            else f"{step}.submit"
        )
        assert not placeholders(text.get(valueless, "")), f"Placeholder in {valueless}"
    assert [key for key in keys if key not in text] == []
    given = set(result.get("description_placeholders") or {})
    unfilled = {key: placeholders(text[key]) - given for key in keys}
    assert {key: missing for key, missing in unfilled.items() if missing} == {}


def repair_issue_id(
    manager: object, args: tuple[object, ...], kwargs: dict[str, object]
) -> str | None:
    """Return the repair whose fix a call starts or continues, if it's a repair's fix.

    Before the call: a fix that it finishes or aborts no longer says.
    """
    if not isinstance(manager, RepairsFlowManager):
        return None
    if "context" in kwargs:
        return cast(RepairsFlowContext, kwargs["context"])["issue_id"]
    return manager.async_get(cast(str, args[0]))["context"]["issue_id"]


@pytest.fixture(name="flow_text", autouse=True)
def fixture_flow_text() -> Iterator[None]:
    """Fail a flow that shows a step, menu option, error or abort reason without English text.

    It also fails when one of their placeholders has no value.
    """

    def checked[M, **P, R](
        method: Callable[Concatenate[M, P], Awaitable[R]],
    ) -> Callable[Concatenate[M, P], Awaitable[R]]:
        async def check(manager: M, /, *args: P.args, **kwargs: P.kwargs) -> R:
            issue_id = repair_issue_id(manager, args, kwargs)
            result = await method(manager, *args, **kwargs)
            await assert_flow_text(
                cast(FlowManager, manager), cast(FlowResult, result), issue_id
            )
            return result

        return check

    with (
        patch.object(FlowManager, "async_init", checked(FlowManager.async_init)),
        patch.object(
            FlowManager, "async_configure", checked(FlowManager.async_configure)
        ),
        # Config flows start here, which doesn't call FlowManager.async_init
        patch.object(
            ConfigEntriesFlowManager,
            "async_init",
            checked(ConfigEntriesFlowManager.async_init),
        ),
    ):
        yield


@pytest.fixture(name="config_entry")
def fixture_config_entry(hass: HomeAssistant) -> MockConfigEntry:
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

    The mock gives the list, or raises, as glocaltokens' get_google_devices() would,
    and the async fetch returns it with an empty home graph, so Google has only the
    devices it lists. mDNS finds no other device.
    """
    google = Mock(return_value=[kitchen_speaker()])

    def fetch(
        client: GLocalAuthenticationTokens, **options: object
    ) -> tuple[list[Device], HomeGraph]:
        return google(client, **options), HomeGraph()

    with (
        # With autospec, a call that glocaltokens wouldn't accept fails
        patch(
            "glocaltokens.client.GLocalAuthenticationTokens.async_get_google_devices_and_home_graph",
            autospec=True,
            side_effect=fetch,
        ),
        no_browser(),
    ):
        yield google


@pytest.fixture(name="replies")
def fixture_replies(aioclient_mock: AiohttpClientMocker) -> Replies:
    """Answer each request to a speaker as this table says when it's sent.

    By address and endpoint, as in test_unsupported_devices, Held to answer only once
    released, or ForToken to answer only requests with that token. The speaker at
    SPEAKER is a Google or Nest speaker.
    """
    replies: Replies = {SPEAKER: dict(SUPPORTED)}
    endpoints = {**ENDPOINTS, API_ENDPOINT_ALARM_DELETE: DELETE}

    async def answer(method: str, url: URL, _data: object) -> AiohttpClientMockResponse:
        # The mock records the request, with its headers, just before asking this
        _, _, _, headers = aioclient_mock.mock_calls[-1]
        reply = replies[str(url.host)][endpoints[url.path_qs.removeprefix("/")]]
        if isinstance(reply, ForToken):
            token = (headers or {}).get(HEADER_CAST_LOCAL_AUTH)
            reply = reply.reply if token == reply.token else HTTPStatus.UNAUTHORIZED
        if isinstance(reply, Held):
            reply.asked.set()
            await reply.released.wait()
            reply = reply.reply
        if isinstance(reply, Exception):
            return AiohttpClientMockResponse(method, url, exc=reply)
        status, body = reply if isinstance(reply, tuple) else (reply, None)
        return AiohttpClientMockResponse(method, url, status=status, json=body)

    for method in ("get", "post"):
        aioclient_mock.request(method, re.compile(""), side_effect=answer)
    return replies


@pytest.fixture(name="two_speakers")
def fixture_two_speakers(google: Mock, replies: Replies) -> None:
    """Make the fake Google list the kitchen and the bedroom speaker, which both answer."""
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    replies[BEDROOM] = dict(SUPPORTED)
