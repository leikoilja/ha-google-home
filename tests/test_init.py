"""Tests for migrating and naming Google Home config entries."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.google_home import async_migrate_entry, async_name_after_account
from custom_components.google_home.const import MASTER_TOKEN_TITLE

# glocaltokens accepts only master tokens of the real length
MASTER_TOKEN = "aas_et/" + "x" * 216


def make_entry(
    data: dict[str, str], minor_version: int = 1, title: str = "Google Home"
) -> Mock:
    """Return a config entry as an older version saved it."""
    return Mock(version=1, minor_version=minor_version, data=data, title=title)


@pytest.mark.parametrize(
    ("master_token", "password"),
    [(MASTER_TOKEN, ""), ("", "app-password"), ("not-a-token", "app-password")],
)
def test_migrate_clears_unused_password(master_token: str, password: str) -> None:
    """Clear a saved app password only when a master token replaces it."""
    hass = Mock()
    entry = make_entry(
        {
            "username": "test@example.com",
            "password": "app-password",
            "master_token": master_token,
            "android_id": "test-android-id",
        }
    )

    assert asyncio.run(async_migrate_entry(hass, entry))

    hass.config_entries.async_update_entry.assert_called_once()
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["minor_version"] == 2
    assert kwargs["data"]["password"] == password
    assert kwargs["data"]["master_token"] == master_token


def test_migrate_skips_current_entries() -> None:
    """Leave entries that are already migrated alone."""
    hass = Mock()

    entry = make_entry({"password": "", "master_token": MASTER_TOKEN}, minor_version=2)
    assert asyncio.run(async_migrate_entry(hass, entry))

    hass.config_entries.async_update_entry.assert_not_called()


def test_name_after_account() -> None:
    """Rename the entry after its account and keep the saved username empty."""
    hass = Mock()
    entry = make_entry(
        {"username": "", "master_token": MASTER_TOKEN}, title=MASTER_TOKEN_TITLE
    )
    client = Mock(async_get_email=AsyncMock(return_value="test@example.com"))

    asyncio.run(async_name_after_account(hass, entry, client))

    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, title="test@example.com"
    )


def test_name_after_account_without_email() -> None:
    """Leave the entry unchanged when Google doesn't give the email address."""
    hass = Mock()
    entry = make_entry({"username": ""}, title=MASTER_TOKEN_TITLE)
    client = Mock(async_get_email=AsyncMock(return_value=None))

    asyncio.run(async_name_after_account(hass, entry, client))

    hass.config_entries.async_update_entry.assert_not_called()
