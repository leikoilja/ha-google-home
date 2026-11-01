"""Tests for signing in, discovering speakers and the options.

Each flow runs through Home Assistant's flow manager. The tests that call the flow's
steps directly check what the flow manager adds nothing to: how glocaltokens
exchanges the cookie and looks up the address, which error a failed sign-in shows
and logs, and which accounts count as the entry's.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from http import HTTPStatus
from ipaddress import ip_address
import json
import logging
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module
from glocaltokens.exceptions import AuthenticationError, HomegraphError
import grpc  # type: ignore[import-untyped]
import pytest
from pytest_homeassistant.common import MockConfigEntry
from requests import Response
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.config_flow import GoogleHomeFlowHandler
from custom_components.google_home.const import (
    BROWSER_TITLE,
    DOMAIN,
    MASTER_TOKEN_TITLE,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import (
    SOURCE_USER,
    SOURCE_ZEROCONF,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

# pylint: enable=wrong-import-order

# A realistic master token: setup checks its length with is_aas_et()
MASTER_TOKEN = "aas_et/" + "x" * 216


@pytest.fixture(name="create_session")
def fixture_create_session() -> Iterator[Mock]:
    """Record the aiohttp sessions Home Assistant creates, without opening them."""
    # Both the shared and the dedicated session helpers create sessions here
    with patch(
        "homeassistant.helpers.aiohttp_client._async_create_clientsession"
    ) as create:
        yield create


@pytest.fixture(name="home_graph", autouse=True)
def fixture_home_graph() -> Iterator[Mock]:
    """Fake Google's home graph, with no homes unless a test gives some.

    Adding the integration asks for the account's homes after signing in.
    """
    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.get_home_graph",
        autospec=True,
        return_value=HomeGraph(),
    ) as home_graph:
        yield home_graph


@pytest.fixture(name="flow")
def fixture_flow(create_session: Mock) -> GoogleHomeFlowHandler:
    """Return a config flow with a fake Home Assistant that runs jobs inline."""
    hass = Mock()
    hass.data = {}
    hass.config_entries.async_entries.return_value = []
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    # Home Assistant creates its shared session long before anyone signs in
    async_get_clientsession(hass)
    create_session.reset_mock()
    flow = GoogleHomeFlowHandler()
    flow.hass = hass
    flow.handler = "google_home"
    flow.context = {"source": "user"}
    return flow


@pytest.fixture(name="client")
def fixture_client() -> Iterator[Mock]:
    """Replace the API client with one that signs in successfully."""
    with patch(
        "custom_components.google_home.config_flow.GlocaltokensApiClient"
    ) as client:
        client.return_value.async_get_master_token = AsyncMock(
            return_value=MASTER_TOKEN
        )
        client.return_value.async_get_access_token = AsyncMock(return_value="access")
        # Like glocaltokens, make up an Android ID only when it isn't given one
        client.return_value.get_android_id = AsyncMock(
            side_effect=lambda: (
                client.call_args.kwargs.get("android_id") or "test-android-id"
            )
        )
        client.return_value.async_get_email = AsyncMock(return_value=None)
        yield client


def test_browser_sign_in_with_glocaltokens(flow: GoogleHomeFlowHandler) -> None:
    """Exchange the cookie through glocaltokens with the Android ID that is saved.

    The address is the one Google gives with the master token.
    """
    with (
        patch(
            "glocaltokens.client.exchange_token",
            return_value={"Token": MASTER_TOKEN, "Email": "test@example.com"},
        ) as exchange,
        patch("glocaltokens.client.perform_oauth", return_value={"Auth": "access"}),
    ):
        result = asyncio.run(
            flow.async_step_browser({"oauth_token": "oauth2_4/cookie"})
        )

    email, cookie, android_id = exchange.call_args.args
    assert (email, cookie) == ("", "oauth2_4/cookie")
    assert result["type"] == "create_entry"
    assert result["data"]["master_token"] == MASTER_TOKEN
    assert result["data"]["username"] == "test@example.com"
    assert result["data"]["android_id"] == android_id


def test_browser_sign_in_rejected_by_google(
    flow: GoogleHomeFlowHandler,
    create_session: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Point out a cookie that Google refuses, logging its reason in one line."""
    with patch(
        "glocaltokens.client.exchange_token",
        return_value={"Error": "BadAuthentication"},
    ):
        result = asyncio.run(
            flow.async_step_browser({"oauth_token": "oauth2_4/cookie"})
        )

    assert result["errors"] == {"base": "oauth-token-invalid"}
    assert_logged_without_traceback(
        caplog, "Failed to sign in: Google gave no master token: BadAuthentication"
    )
    create_session.assert_not_called()


def test_master_token_rejected_by_google(
    flow: GoogleHomeFlowHandler,
    create_session: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Point out a master token that Google refuses, logging its reason in one line."""
    with patch(
        "glocaltokens.client.perform_oauth",
        return_value={"Error": "BadAuthentication"},
    ):
        result = asyncio.run(
            flow.async_step_master_token({"master_token": MASTER_TOKEN})
        )

    assert result["errors"] == {"base": "master-token-invalid"}
    assert_logged_without_traceback(
        caplog, "Failed to sign in: Google gave no access token: BadAuthentication"
    )
    create_session.assert_not_called()


def test_sign_in_without_network(
    flow: GoogleHomeFlowHandler, client: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log the network error in one line when Google can't be reached."""
    client.return_value.async_get_master_token.side_effect = RequestException(
        "No network"
    )

    result = asyncio.run(flow.async_step_master_token({"master_token": MASTER_TOKEN}))

    assert result["errors"] == {"base": "google-unreachable"}
    assert_logged_without_traceback(caplog, "Failed to sign in: No network")


def assert_logged_without_traceback(
    caplog: pytest.LogCaptureFixture, message: str
) -> None:
    """Check that the integration logged only this warning, without a traceback."""
    records = [
        record
        for record in caplog.records
        if record.name == "custom_components.google_home"
    ]
    assert [(record.levelno, record.getMessage()) for record in records] == [
        (logging.WARNING, message)
    ]
    assert records[0].exc_info is None


@pytest.mark.parametrize(
    "error",
    [
        RequestException("No network"),
        AuthenticationError("Google gave no master token", "BadAuthentication"),
    ],
)
def test_get_email_failure(error: Exception) -> None:
    """Treat a failed email lookup as no email address, so setup still succeeds."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    client = GlocaltokensApiClient(hass, Mock(), master_token=MASTER_TOKEN)

    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.get_email",
        side_effect=error,
    ):
        assert asyncio.run(client.async_get_email()) is None


ENGLISH = json.loads(
    (
        Path(__file__).parents[1] / "custom_components/google_home/translations/en.json"
    ).read_text(encoding="utf-8")
)
OLD_MASTER_TOKEN = "aas_et/" + "o" * 216
OTHER_ACCOUNT_MASTER_TOKEN = "aas_et/" + "a" * 216
MASTER_TOKEN_INPUT = {"master_token": MASTER_TOKEN}


def start_reauth(
    flow: GoogleHomeFlowHandler, username: str, title: str
) -> ConfigFlowResult:
    """Start signing in again to an entry whose master token Google rejects."""
    entry = Mock(
        entry_id="entry",
        title=title,
        data={
            "master_token": OLD_MASTER_TOKEN,
            "username": username,
            "password": "",
            "android_id": "old-android-id",
        },
    )
    cast(Mock, flow.hass.config_entries).async_get_known_entry.return_value = entry
    flow.context = {"source": "reauth", "entry_id": "entry"}
    return asyncio.run(flow.async_step_reauth(entry.data))


def sign_in_again(flow: GoogleHomeFlowHandler) -> ConfigFlowResult:
    """Submit a master token as Home Assistant does when signing in again."""
    return asyncio.run(flow.async_step_reauth_master_token(MASTER_TOKEN_INPUT))


def assert_saved(flow: GoogleHomeFlowHandler, username: str) -> None:
    """Check that the entry got the new master token, kept its Android ID and is reloaded once."""
    config_entries = cast(Mock, flow.hass.config_entries)
    config_entries.async_update_entry.assert_called_once()
    assert config_entries.async_update_entry.call_args.kwargs["data"] == {
        "master_token": MASTER_TOKEN,
        "username": username,
        "password": "",
        "android_id": "old-android-id",
    }
    config_entries.async_schedule_reload.assert_called_once_with("entry")


def assert_not_saved(flow: GoogleHomeFlowHandler) -> None:
    """Check that the entry and its master token stay as they were."""
    config_entries = cast(Mock, flow.hass.config_entries)
    config_entries.async_update_entry.assert_not_called()
    config_entries.async_schedule_reload.assert_not_called()


@pytest.mark.parametrize(
    ("saved", "email", "same"),
    [
        ("Test@Example.com", "test@example.com", True),
        # Gmail ignores dots, and googlemail.com is the same as gmail.com
        ("johndoe@gmail.com", "john.doe@gmail.com", True),
        ("john.doe@googlemail.com", "johndoe@gmail.com", True),
        # Other addresses with different dots are different accounts
        ("johndoe@example.com", "john.doe@example.com", False),
    ],
)
def test_reauth_account_spelled_differently(
    flow: GoogleHomeFlowHandler, client: Mock, saved: str, email: str, same: bool
) -> None:
    """Match the address that older versions saved as typed with the one Google gives."""
    client.return_value.async_get_email.return_value = email
    start_reauth(flow, saved, saved)

    result = sign_in_again(flow)

    if same:
        assert result["reason"] == "reauth_successful"
        assert_saved(flow, email)
    else:
        assert result["errors"] == {"base": "other-account"}
        assert_not_saved(flow)


def test_reauth_account_in_title(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Accept the account an older entry is named after, though it saved another address.

    Older versions saved the address typed for a master token entry, and its
    generic title is renamed after the address Google gives.
    """
    client.return_value.async_get_email.return_value = "test@example.com"
    start_reauth(flow, "alias@example.com", "test@example.com")

    result = sign_in_again(flow)

    assert result["reason"] == "reauth_successful"
    assert_saved(flow, "test@example.com")


@pytest.mark.parametrize(
    ("username", "title", "email", "saved"),
    [
        # Google doesn't give the new token's address: keep the saved one
        ("test@example.com", "test@example.com", None, "test@example.com"),
        # The entry doesn't know its account
        ("", MASTER_TOKEN_TITLE, "test@example.com", "test@example.com"),
        ("", BROWSER_TITLE, None, ""),
    ],
)
def test_reauth_account_unknown(
    flow: GoogleHomeFlowHandler,
    client: Mock,
    username: str,
    title: str,
    email: str | None,
    saved: str,
) -> None:
    """Sign in again when the account can't be compared, saving the address if Google gives it."""
    client.return_value.async_get_email.return_value = email
    start_reauth(flow, username, title)

    result = sign_in_again(flow)

    assert result["reason"] == "reauth_successful"
    assert_saved(flow, saved)


def answered(status: HTTPStatus) -> HTTPError:
    """Return the error glocaltokens raises when Google answers with this status."""
    response = Response()
    response.status_code = status
    return HTTPError(response=response)


@contextmanager
def google_answers(answer: dict[str, str] | Exception) -> Iterator[None]:
    """Give this answer to glocaltokens' requests for a master token and an access token."""
    reply = (
        {"side_effect": answer}
        if isinstance(answer, Exception)
        else {"return_value": answer}
    )
    with (
        patch("glocaltokens.client.exchange_token", **reply),
        patch("glocaltokens.client.perform_oauth", **reply),
    ):
        yield


@pytest.mark.parametrize("reauth", [False, True], ids=["setup", "reauth"])
@pytest.mark.parametrize(
    ("answer", "error"),
    [
        # None is the form's own error for a cookie or master token Google refuses
        pytest.param({"Error": "BadAuthentication"}, None, id="rejected"),
        pytest.param({"Error": "NeedsBrowser"}, "google-rejected", id="other-reason"),
        pytest.param({}, "google-rejected", id="no-reason"),
        pytest.param(answered(HTTPStatus.SERVICE_UNAVAILABLE), "google-busy", id="503"),
        pytest.param(answered(HTTPStatus.TOO_MANY_REQUESTS), "google-busy", id="429"),
        pytest.param(
            RequestsConnectionError("Connection refused"),
            "google-unreachable",
            id="unreachable",
        ),
        pytest.param(ReadTimeout(), "google-unreachable", id="timeout"),
    ],
)
@pytest.mark.parametrize(
    ("method", "user_input", "rejected"),
    [
        pytest.param(
            "browser",
            {"oauth_token": "oauth2_4/cookie"},
            "oauth-token-invalid",
            id="browser",
        ),
        pytest.param(
            "master_token",
            MASTER_TOKEN_INPUT,
            "master-token-invalid",
            id="master-token",
        ),
    ],
)
def test_sign_in_failed(
    flow: GoogleHomeFlowHandler,
    method: str,
    user_input: dict[str, str],
    rejected: str,
    answer: dict[str, str] | Exception,
    error: str | None,
    reauth: bool,
) -> None:
    """Show the form again with why Google gave no token, so the entry stays unchanged."""
    step = method
    if reauth:
        start_reauth(flow, "test@example.com", "test@example.com")
        step = f"reauth_{method}"

    with google_answers(answer):
        result = asyncio.run(getattr(flow, f"async_step_{step}")(user_input))

    assert result["type"] == "form"
    assert result["step_id"] == step
    assert result["errors"] == {"base": error or rejected}
    assert result["errors"]["base"] in ENGLISH["config"]["error"]
    assert_not_saved(flow)


def test_master_token_in_unknown_format(flow: GoogleHomeFlowHandler) -> None:
    """Attribute a master token that can't be right to Google, not to the cookie."""
    with google_answers({"Token": "not-a-master-token"}):
        result = asyncio.run(
            flow.async_step_browser({"oauth_token": "oauth2_4/cookie"})
        )

    assert result["errors"] == {"base": "google-rejected"}


# Signing in, discovering speakers and the options through Home Assistant's flow
# manager, which checks the input against the form, starts signing in again and saves
# the entry

EMAIL = "test@example.com"
# The master token that signing in gets, other than the entry's
NEW_MASTER_TOKEN = "aas_et/" + "n" * 216
SIGN_IN_INPUT = {
    "browser": {"oauth_token": "oauth2_4/cookie"},
    "master_token": {"master_token": NEW_MASTER_TOKEN},
}
METHODS = list(SIGN_IN_INPUT)
# Signing in to another account than the entry's, which gives OTHER_ACCOUNT_MASTER_TOKEN
OTHER_ACCOUNT_INPUT = {
    "browser": {"oauth_token": "oauth2_4/other-cookie"},
    "master_token": {"master_token": OTHER_ACCOUNT_MASTER_TOKEN},
}


@pytest.fixture(name="mock_setup_entry")
async def fixture_mock_setup_entry(hass: HomeAssistant) -> AsyncIterator[AsyncMock]:
    """Set up and unload an entry without asking Google or the speakers."""
    with (
        patch(
            "custom_components.google_home.async_setup_entry", return_value=None
        ) as setup_entry,
        patch("custom_components.google_home.async_unload_entry", return_value=None),
    ):
        yield setup_entry
        # Home Assistant unloads it when it stops, after these patches end
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture(name="sign_in")
def fixture_sign_in() -> Iterator[Mock]:
    """Fake Google accepting any cookie or master token, as test@example.com's.

    It exchanges a cookie for NEW_MASTER_TOKEN, and gives an access token for any
    master token. glocaltokens' requests to it are recorded.
    """
    with (
        patch(
            "glocaltokens.client.exchange_token",
            return_value={"Token": NEW_MASTER_TOKEN},
        ) as exchange_token,
        patch(
            "glocaltokens.client.perform_oauth", return_value={"Auth": "access"}
        ) as perform_oauth,
        # Google's userinfo endpoint, which gives the address, isn't simulated
        patch(
            "glocaltokens.client.GLocalAuthenticationTokens.get_email",
            autospec=True,
            return_value=EMAIL,
        ) as get_email,
    ):
        yield Mock(
            exchange_token=exchange_token,
            perform_oauth=perform_oauth,
            get_email=get_email,
        )


def sent_to_google(sign_in: Mock) -> list[tuple[str, str]]:
    """Return the cookie or master token and the Android ID of each request to Google."""
    return [
        (call.args[1], call.args[2])
        for call in sign_in.exchange_token.call_args_list
        + sign_in.perform_oauth.call_args_list
    ]


async def choose(hass: HomeAssistant, method: str) -> ConfigFlowResult:
    """Start adding the integration, and choose how to sign in."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": method}
    )


async def submit(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict[str, str]
) -> ConfigFlowResult:
    """Submit the form that the flow shows."""
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("method", "pasted", "email", "title"),
    [
        pytest.param("browser", " oauth2_4/cookie\n", EMAIL, EMAIL, id="browser"),
        pytest.param(
            "browser", "oauth2_4/cookie", None, BROWSER_TITLE, id="browser-no-email"
        ),
        pytest.param(
            "master_token", f" {NEW_MASTER_TOKEN}\n", EMAIL, EMAIL, id="master-token"
        ),
        pytest.param(
            "master_token",
            NEW_MASTER_TOKEN,
            None,
            MASTER_TOKEN_TITLE,
            id="master-token-no-email",
        ),
    ],
)
async def test_sign_in(
    hass: HomeAssistant,
    sign_in: Mock,
    method: str,
    pasted: str,
    email: str | None,
    title: str,
) -> None:
    """Save the master token that signing in gets, named after its account if Google gives it.

    Google gets the pasted value without the spaces around it, and the Android ID
    that is saved with the master token.
    """
    sign_in.get_email.return_value = email
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["browser", "master_token"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": method}
    )
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, method)
    [field] = SIGN_IN_INPUT[method]
    result = await submit(hass, result, {field: pasted})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    [entry] = hass.config_entries.async_entries(DOMAIN)
    sent = sent_to_google(sign_in)
    android_id = sent[0][1]
    assert entry.title == title
    assert entry.data == {
        "master_token": NEW_MASTER_TOKEN,
        "username": email or "",
        "password": "",
        "android_id": android_id,
    }
    assert pasted.strip() in {token for token, _ in sent}
    assert {sent_id for _, sent_id in sent} == {android_id}


# The account's homes
HOMES = HomeGraph(
    homes=[
        HomeGraph.Home(id="home-id", display_name="Home"),
        HomeGraph.Home(id="flat-id", display_name="Flat"),
    ]
)


@pytest.mark.usefixtures("mock_setup_entry", "sign_in")
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(
            HomeGraph(homes=[HomeGraph.Home(id="home-id", display_name="Home")]),
            id="one-home",
        ),
        pytest.param(
            HomegraphError(grpc.StatusCode.UNAVAILABLE, "Unavailable"),
            id="no-home-graph",
        ),
        pytest.param(RequestsConnectionError(), id="unreachable"),
    ],
)
async def test_sign_in_adds_every_home(
    hass: HomeAssistant, home_graph: Mock, answer: HomeGraph | Exception
) -> None:
    """Add the integration straight after signing in without a choice of homes, or the homes.

    Every home's devices are then added, until the options exclude some.
    """
    home_graph.side_effect = [answer]
    result = await choose(hass, "master_token")
    result = await submit(hass, result, SIGN_IN_INPUT["master_token"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.options == {}


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("method", "pasted", "error"),
    [
        pytest.param(
            "browser",
            {"oauth_token": "SAPISID=abc"},
            {"oauth_token": "oauth-token-format"},
            id="oauth-token-format",
        ),
        pytest.param(
            "master_token",
            {"master_token": NEW_MASTER_TOKEN[:100]},
            {"master_token": "master-token-format"},
            id="master-token-format",
        ),
    ],
)
async def test_sign_in_format_error(
    hass: HomeAssistant,
    sign_in: Mock,
    method: str,
    pasted: dict[str, str],
    error: dict[str, str],
) -> None:
    """Point out a value that can't be the cookie or master token without asking Google.

    Pasting the right one then adds the integration.
    """
    result = await submit(hass, await choose(hass, method), pasted)

    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, method)
    assert result["errors"] == error
    assert sent_to_google(sign_in) == []

    result = await submit(hass, result, SIGN_IN_INPUT[method])

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry", "sign_in")
@pytest.mark.parametrize(
    ("method", "answer", "error"),
    [
        pytest.param(
            "browser",
            {"Error": "BadAuthentication"},
            "oauth-token-invalid",
            id="oauth-token-invalid",
        ),
        pytest.param(
            "master_token",
            {"Error": "BadAuthentication"},
            "master-token-invalid",
            id="master-token-invalid",
        ),
        pytest.param(
            "browser",
            {"Error": "NeedsBrowser"},
            "google-rejected",
            id="google-rejected",
        ),
        pytest.param(
            "master_token",
            RequestsConnectionError("Connection refused"),
            "google-unreachable",
            id="google-unreachable",
        ),
        pytest.param(
            "browser",
            answered(HTTPStatus.SERVICE_UNAVAILABLE),
            "google-busy",
            id="google-busy",
        ),
    ],
)
async def test_sign_in_error(
    hass: HomeAssistant,
    method: str,
    answer: dict[str, str] | Exception,
    error: str,
) -> None:
    """Show why Google gave no master token on the same form, without adding the integration.

    Once Google gives one, submitting the form again adds it.
    """
    result = await choose(hass, method)
    with google_answers(answer):
        result = await submit(hass, result, SIGN_IN_INPUT[method])

    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, method)
    assert result["errors"] == {"base": error}
    assert hass.config_entries.async_entries(DOMAIN) == []

    result = await submit(hass, result, SIGN_IN_INPUT[method])

    assert result["type"] is FlowResultType.CREATE_ENTRY


def speaker(name: str, address: str) -> ZeroconfServiceInfo:
    """Return what zeroconf finds of a speaker, which signing in doesn't use."""
    return ZeroconfServiceInfo(
        ip_address=ip_address(address),
        ip_addresses=[ip_address(address)],
        port=8009,
        hostname=f"{name}.local.",
        type="_googlecast._tcp.local.",
        name=f"{name}._googlecast._tcp.local.",
        properties={"fn": name},
    )


async def discover(hass: HomeAssistant, name: str, address: str) -> ConfigFlowResult:
    """Start adding the integration for a speaker that zeroconf found."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=speaker(name, address)
    )


# Adding the integration by hand, and for a speaker that zeroconf found
SOURCES = [
    pytest.param(SOURCE_USER, None, id="user"),
    pytest.param(SOURCE_ZEROCONF, speaker("Kitchen", "192.168.1.10"), id="zeroconf"),
]


@pytest.mark.usefixtures("enable_custom_integrations", "mock_setup_entry", "sign_in")
async def test_discovery(hass: HomeAssistant) -> None:
    """Offer the same sign-in as adding the integration when a speaker is found."""
    result = await discover(hass, "Kitchen", "192.168.1.10")

    assert (result["type"], result["step_id"]) == (FlowResultType.MENU, "user")
    assert result["menu_options"] == ["browser", "master_token"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "browser"}
    )
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "browser")
    result = await submit(hass, result, SIGN_IN_INPUT["browser"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.data["master_token"] == NEW_MASTER_TOKEN


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(("source", "data"), SOURCES)
async def test_discovery_in_progress(
    hass: HomeAssistant, source: str, data: ZeroconfServiceInfo | None
) -> None:
    """Abort the flow of another speaker found while the integration is being added.

    The open flow, whether found or started by hand, adds one entry with all the
    account's devices.
    """
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=data
    )

    result = await discover(hass, "Bedroom", "192.168.1.11")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"
    assert [
        flow["flow_id"]
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    ] == [first["flow_id"]]


@pytest.mark.usefixtures("config_entry")
@pytest.mark.parametrize(("source", "data"), SOURCES)
async def test_single_entry(
    hass: HomeAssistant, source: str, data: ZeroconfServiceInfo | None
) -> None:
    """Refuse to add the integration again, also for a speaker found later.

    Its entry has all the account's devices.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=data
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.parametrize("method", METHODS)
async def test_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    sign_in: Mock,
    home_graph: Mock,
    mock_setup_entry: AsyncMock,
    method: str,
) -> None:
    """Save the new master token in the entry and reload it, keeping its Android ID.

    The menu names the entry. The forms have text of their own: the setup forms say
    to add the integration again to choose another way to sign in, which can't be
    done while the entry exists. The homes aren't offered again, and the excluded
    ones stay excluded.
    """
    home_graph.return_value = HOMES
    hass.config_entries.async_update_entry(
        config_entry, title="Home", options={"excluded_homes": ["flat-id"]}
    )
    result = await config_entry.start_reauth_flow(hass)
    assert (result["type"], result["step_id"]) == (FlowResultType.MENU, "reauth")
    assert result["menu_options"] == ["browser", "master_token"]
    assert result["description_placeholders"] == {"name": "Home"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": method}
    )
    assert result["step_id"] == f"reauth_{method}"
    text = ENGLISH["config"]["step"][result["step_id"]]["description"]
    assert "add the integration again" not in text

    result = await submit(hass, result, SIGN_IN_INPUT[method])
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert hass.config_entries.async_entries(DOMAIN) == [config_entry]
    assert config_entry.data == {
        "master_token": NEW_MASTER_TOKEN,
        "username": EMAIL,
        "password": "",
        "android_id": "android-id",
    }
    assert {android_id for _, android_id in sent_to_google(sign_in)} == {"android-id"}
    assert config_entry.options == {"excluded_homes": ["flat-id"]}
    mock_setup_entry.assert_awaited_once()
    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("username", "title"),
    [
        (EMAIL, "Home"),
        # A master token entry of an older version, named after its account
        # without saving its address
        ("", EMAIL),
    ],
)
@pytest.mark.parametrize("method", METHODS)
async def test_reauth_other_account(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    sign_in: Mock,
    username: str,
    title: str,
    method: str,
) -> None:
    """Refuse another Google account on the same form, so the entry's can sign in at once.

    Nothing of the other account is saved, then or with the entry's account.
    """
    hass.config_entries.async_update_entry(
        config_entry, title=title, data={**config_entry.data, "username": username}
    )
    saved = dict(config_entry.data)
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": method}
    )
    sign_in.get_email.return_value = "other@example.com"
    sign_in.exchange_token.return_value = {"Token": OTHER_ACCOUNT_MASTER_TOKEN}
    result = await submit(hass, result, OTHER_ACCOUNT_INPUT[method])

    assert (result["type"], result["step_id"]) == (
        FlowResultType.FORM,
        f"reauth_{method}",
    )
    assert result["errors"] == {"base": "other-account"}
    assert config_entry.data == saved

    sign_in.get_email.return_value = EMAIL
    sign_in.exchange_token.return_value = {"Token": NEW_MASTER_TOKEN}
    result = await submit(hass, result, SIGN_IN_INPUT[method])

    assert result["reason"] == "reauth_successful"
    assert config_entry.data["master_token"] == NEW_MASTER_TOKEN
    assert config_entry.data["username"] == EMAIL


@pytest.mark.parametrize(
    ("options", "interval"), [({}, 15), ({"update_interval": 180}, 180)]
)
async def test_options_show_default_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    options: dict[str, object],
    interval: int,
) -> None:
    """Fill in 15 seconds for an entry without a saved interval, and show it as the default.

    An entry that saved another interval keeps it, and still sees the default in
    the label. Home Assistant can't show the label without its placeholder's value.
    """
    hass.config_entries.async_update_entry(config_entry, options=options)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    # What the form fills in when nothing is entered
    assert schema({})["update_interval"] == interval
    text = ENGLISH["options"]["step"]["init"]
    placeholders = result["description_placeholders"] or {}
    label = text["data"]["update_interval"].format_map(placeholders)
    assert "Default: 15 (seconds)" in label


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Ask for IP addresses, as requests to devices are built from them.

    Then save known hosts without blanks, surrounding spaces and repeats, in order.
    The entry isn't loaded, so the homes aren't offered, and the excluded ones stay
    excluded.
    """
    hass.config_entries.async_update_entry(
        config_entry,
        options={"known_hosts": ["10.0.1.5"], "excluded_homes": ["flat-id"]},
    )
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 180, "known_hosts": ["kitchen.local"]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"known_hosts": "known-host-not-ip"}
    assert config_entry.options == {
        "known_hosts": ["10.0.1.5"],
        "excluded_homes": ["flat-id"],
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "update_interval": 180,
            "known_hosts": [" 10.0.1.5 ", "", "fd00::5", "10.0.1.5"],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "update_interval": 180,
        "known_hosts": ["10.0.1.5", "fd00::5"],
        "bluetooth_tracking": False,
        "bluetooth_excluded_speakers": [],
        "excluded_homes": ["flat-id"],
    }
