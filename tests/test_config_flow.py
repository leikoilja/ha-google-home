"""Tests for Google Home setup validation."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus
import json
import logging
from pathlib import Path
import re
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

from glocaltokens.exceptions import AuthenticationError
import pytest
from requests import Response
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.config_flow import GoogleHomeFlowHandler
from custom_components.google_home.const import BROWSER_TITLE, MASTER_TOKEN_TITLE

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .test_known_hosts import make_options_flow

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


def test_menu(flow: GoogleHomeFlowHandler) -> None:
    """Offer browser sign-in first, then the master token."""
    result = asyncio.run(flow.async_step_user())

    assert result["type"] == "menu"
    assert result["menu_options"] == ["browser", "master_token"]


def test_browser_sign_in(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Save the exchanged master token under the email Google returns for it."""
    client.return_value.async_get_email = AsyncMock(return_value="test@example.com")

    result = asyncio.run(flow.async_step_browser({"oauth_token": " oauth2_4/cookie\n"}))

    assert "username" not in client.call_args.kwargs
    assert client.call_args.kwargs["oauth_token"] == "oauth2_4/cookie"
    assert result["type"] == "create_entry"
    assert result["title"] == "test@example.com"
    assert result["data"] == {
        "master_token": MASTER_TOKEN,
        "username": "test@example.com",
        "password": "",
        "android_id": "test-android-id",
    }


@pytest.mark.usefixtures("client")
def test_browser_sign_in_without_email(flow: GoogleHomeFlowHandler) -> None:
    """Still save the master token when Google doesn't give the email address."""
    result = asyncio.run(flow.async_step_browser({"oauth_token": "oauth2_4/cookie"}))

    assert result["type"] == "create_entry"
    assert result["title"] == "Google Home (browser)"
    assert result["data"]["username"] == ""


def test_browser_cookie_format(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Point out a value that isn't the oauth_token cookie without asking Google."""
    result = asyncio.run(flow.async_step_browser({"oauth_token": "SAPISID=abc"}))

    assert result["errors"] == {"oauth_token": "oauth-token-format"}
    client.assert_not_called()


def test_browser_sign_in_with_glocaltokens(flow: GoogleHomeFlowHandler) -> None:
    """Exchange the cookie through glocaltokens with the Android ID that is saved."""
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


def test_master_token(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Save a master token that Google accepts, named after its account."""
    client.return_value.async_get_email.return_value = "test@example.com"

    result = asyncio.run(flow.async_step_master_token({"master_token": MASTER_TOKEN}))

    assert result["type"] == "create_entry"
    assert result["title"] == "test@example.com"
    assert result["data"]["master_token"] == MASTER_TOKEN
    assert result["data"]["username"] == "test@example.com"


@pytest.mark.usefixtures("client")
def test_master_token_without_email(flow: GoogleHomeFlowHandler) -> None:
    """Still save the master token when Google doesn't give the email address."""
    result = asyncio.run(flow.async_step_master_token({"master_token": MASTER_TOKEN}))

    assert result["type"] == "create_entry"
    assert result["title"] == "Google Home (master_token)"
    assert result["data"]["username"] == ""


def test_master_token_format(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Point out an incomplete master token without asking Google."""
    result = asyncio.run(
        flow.async_step_master_token({"master_token": MASTER_TOKEN[:100]})
    )

    assert result["errors"] == {"master_token": "master-token-format"}
    client.assert_not_called()


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
SIGN_IN_STEPS = [
    pytest.param("reauth_browser", {"oauth_token": "oauth2_4/cookie"}, id="browser"),
    pytest.param("reauth_master_token", MASTER_TOKEN_INPUT, id="master-token"),
]


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


def sign_in_again(
    flow: GoogleHomeFlowHandler, step: str, user_input: dict[str, str]
) -> ConfigFlowResult:
    """Submit a sign-in form as Home Assistant does when signing in again."""
    steps = {
        "reauth_browser": flow.async_step_reauth_browser,
        "reauth_master_token": flow.async_step_reauth_master_token,
    }
    return asyncio.run(steps[step](user_input))


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


def test_reauth_menu(flow: GoogleHomeFlowHandler) -> None:
    """Offer both ways to sign in again, naming the entry."""
    result = start_reauth(flow, "test@example.com", "Home")

    assert result["type"] == "menu"
    assert result["step_id"] == "reauth"
    assert result["menu_options"] == ["browser", "master_token"]
    assert result["description_placeholders"] == {"name": "Home"}
    menu_text = ENGLISH["config"]["step"]["reauth"]["menu_options"]
    assert list(menu_text) == result["menu_options"]


@pytest.mark.parametrize("method", ["browser", "master_token"])
def test_reauth_forms_have_text(flow: GoogleHomeFlowHandler, method: str) -> None:
    """Show the sign-in forms with text of their own, with every placeholder filled in.

    The setup forms say to add the integration again to choose another way to sign
    in, which can't be done while the entry exists.
    """
    start_reauth(flow, "test@example.com", "test@example.com")

    result = asyncio.run(getattr(flow, f"async_step_{method}")())

    assert result["type"] == "form"
    assert result["step_id"] == f"reauth_{method}"
    text = ENGLISH["config"]["step"][result["step_id"]]
    assert text["title"]
    placeholders = set(re.findall(r"{(\w+)}", text["description"]))
    assert placeholders <= set(result["description_placeholders"] or {})
    assert "add the integration again" not in text["description"]


@pytest.mark.parametrize(
    ("options", "interval"), [({}, 15), ({"update_interval": 180}, 180)]
)
def test_options_show_default_interval(
    options: dict[str, object], interval: int
) -> None:
    """Fill in 15 seconds for an entry without a saved interval, and show it as the default.

    An entry that saved another interval keeps it, and still sees the default in
    the label. Home Assistant can't show the label without its placeholder's value.
    """
    result = asyncio.run(make_options_flow(options).async_step_init())

    assert result["type"] == "form"
    schema = result["data_schema"]
    assert schema is not None
    # What the form fills in when nothing is entered
    assert schema({})["update_interval"] == interval
    text = ENGLISH["options"]["step"]["init"]
    placeholders = result["description_placeholders"] or {}
    assert set(re.findall(r"{(\w+)}", json.dumps(text))) <= set(placeholders)
    label = text["data"]["update_interval"].format_map(placeholders)
    assert "Default: 15 (seconds)" in label


@pytest.mark.parametrize(("step", "user_input"), SIGN_IN_STEPS)
def test_reauth(
    flow: GoogleHomeFlowHandler, client: Mock, step: str, user_input: dict[str, str]
) -> None:
    """Save the new master token in the entry and reload it, without a new entry."""
    client.return_value.async_get_email.return_value = "test@example.com"
    start_reauth(flow, "test@example.com", "Home")

    result = sign_in_again(flow, step, user_input)

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert_saved(flow, "test@example.com")


@pytest.mark.parametrize(
    ("username", "title"),
    [
        ("test@example.com", "Home"),
        # A master token entry of an older version, named after its account
        # without saving its address
        ("", "test@example.com"),
    ],
)
@pytest.mark.parametrize(("step", "user_input"), SIGN_IN_STEPS)
def test_reauth_other_account(
    flow: GoogleHomeFlowHandler,
    client: Mock,
    username: str,
    title: str,
    step: str,
    user_input: dict[str, str],
) -> None:
    """Refuse another Google account on the same form, so the entry's can sign in at once.

    Nothing of the other account is saved, then or with the entry's account.
    """
    client.return_value.async_get_email.return_value = "other@example.com"
    client.return_value.async_get_master_token.return_value = OTHER_ACCOUNT_MASTER_TOKEN
    start_reauth(flow, username, title)

    result = sign_in_again(flow, step, user_input)

    assert result["type"] == "form"
    assert result["step_id"] == step
    assert result["errors"] == {"base": "other-account"}
    assert result["errors"]["base"] in ENGLISH["config"]["error"]
    assert_not_saved(flow)

    client.return_value.async_get_email.return_value = "test@example.com"
    client.return_value.async_get_master_token.return_value = MASTER_TOKEN
    result = sign_in_again(flow, step, user_input)

    assert result["reason"] == "reauth_successful"
    assert_saved(flow, "test@example.com")


@pytest.mark.parametrize(("step", "user_input"), SIGN_IN_STEPS)
def test_reauth_keeps_android_id(
    flow: GoogleHomeFlowHandler, step: str, user_input: dict[str, str]
) -> None:
    """Sign in again to Google with the entry's Android ID, and save it unchanged."""
    start_reauth(flow, "test@example.com", "Home")

    with (
        patch(
            "glocaltokens.client.exchange_token", return_value={"Token": MASTER_TOKEN}
        ) as exchange,
        patch(
            "glocaltokens.client.perform_oauth", return_value={"Auth": "access"}
        ) as oauth,
        # Not simulated: the master token step looks up the address elsewhere
        patch.object(
            GlocaltokensApiClient, "async_get_email", return_value="test@example.com"
        ),
    ):
        result = sign_in_again(flow, step, user_input)

    assert result["reason"] == "reauth_successful"
    calls = exchange.call_args_list + oauth.call_args_list
    assert {call.args[2] for call in calls} == {"old-android-id"}
    config_entries = cast(Mock, flow.hass.config_entries)
    saved = config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved["android_id"] == "old-android-id"


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

    result = sign_in_again(flow, "reauth_master_token", MASTER_TOKEN_INPUT)

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

    result = sign_in_again(flow, "reauth_master_token", MASTER_TOKEN_INPUT)

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

    result = sign_in_again(flow, "reauth_master_token", MASTER_TOKEN_INPUT)

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
