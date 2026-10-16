"""Tests for Google Home setup validation."""

import asyncio
from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from requests.exceptions import RequestException

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.config_flow import GoogleHomeFlowHandler
from custom_components.google_home.exceptions import InvalidMasterToken

# glocaltokens accepts only master tokens of the real length
MASTER_TOKEN = "aas_et/" + "x" * 216


@pytest.fixture(name="flow")
def fixture_flow() -> Iterator[GoogleHomeFlowHandler]:
    """Return a config flow with a fake Home Assistant that runs jobs inline."""
    hass = Mock()
    hass.config_entries.async_entries.return_value = []
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    flow = GoogleHomeFlowHandler()
    flow.hass = hass
    flow.handler = "google_home"
    flow.context = {"source": "user"}
    with patch("custom_components.google_home.config_flow.async_create_clientsession"):
        yield flow


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
        client.return_value.get_android_id = AsyncMock(return_value="test-android-id")
        client.return_value.async_get_email = AsyncMock(return_value=None)
        yield client


def reject_sign_in(client: Mock) -> None:
    """Make Google refuse the credentials."""
    client.return_value.async_get_master_token.side_effect = InvalidMasterToken


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


def test_browser_sign_in_rejected(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Ask for a new cookie when Google doesn't accept it."""
    reject_sign_in(client)

    result = asyncio.run(flow.async_step_browser({"oauth_token": "oauth2_4/used"}))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "oauth-token-invalid"}


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


def test_master_token_rejected(flow: GoogleHomeFlowHandler, client: Mock) -> None:
    """Reject a master token that Google refuses."""
    reject_sign_in(client)

    result = asyncio.run(flow.async_step_master_token({"master_token": MASTER_TOKEN}))

    assert result["errors"] == {"base": "master-token-invalid"}


def test_get_email_failure() -> None:
    """Treat a failed email lookup as no email address, so setup still succeeds."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    client = GlocaltokensApiClient(hass, Mock(), master_token=MASTER_TOKEN)

    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.get_email",
        side_effect=RequestException("No network"),
    ):
        assert asyncio.run(client.async_get_email()) is None
