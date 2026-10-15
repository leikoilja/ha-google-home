"""Tests for Google Home setup validation."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.google_home.config_flow import GoogleHomeFlowHandler


@pytest.mark.parametrize(
    ("password_length", "accepted"), [(99, True), (100, True), (101, False)]
)
def test_password_length(password_length: int, accepted: bool) -> None:
    """Accept passwords up to 100 characters and reject longer ones before authentication."""
    hass = Mock()
    hass.config_entries.async_entries.return_value = []
    flow = GoogleHomeFlowHandler()
    flow.hass = hass
    flow.handler = "google_home"
    flow.context = {"source": "user"}
    password = "x" * password_length

    with (
        patch("custom_components.google_home.config_flow.async_create_clientsession"),
        patch(
            "custom_components.google_home.config_flow.GlocaltokensApiClient"
        ) as client,
    ):
        client.return_value.async_get_master_token = AsyncMock(
            return_value="aas_et/test-token"
        )
        client.return_value.get_android_id = AsyncMock(return_value="test-android-id")
        result = asyncio.run(
            flow.async_step_user(
                {
                    "username": "test@example.com",
                    "password": password,
                    "master_token": "",
                }
            )
        )

        if accepted:
            assert result["type"] == "create_entry"
            assert result["data"]["password"] == password
            client.assert_called_once()
            assert client.call_args.kwargs["password"] == password
            client.return_value.async_get_master_token.assert_awaited_once()
        else:
            assert result["type"] == "form"
            assert result["errors"] == {"base": "pass-len"}
            assert result["description_placeholders"] is not None
            assert result["description_placeholders"]["max_password_length"] == "100"
            client.assert_not_called()
