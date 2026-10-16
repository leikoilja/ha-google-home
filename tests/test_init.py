"""Tests for migrating and naming config entries and deleting devices."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.google_home import (
    async_migrate_entry,
    async_name_after_account,
    async_remove_config_entry_device,
)
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    BROWSER_TITLE,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    MASTER_TOKEN_TITLE,
)
from custom_components.google_home.models import GoogleHomeDevice

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


@pytest.mark.parametrize("title", [MASTER_TOKEN_TITLE, BROWSER_TITLE])
def test_name_after_account(title: str) -> None:
    """Rename the entry after its account and keep the saved username empty."""
    hass = Mock()
    entry = make_entry({"username": "", "master_token": MASTER_TOKEN}, title=title)
    client = Mock(async_get_email=AsyncMock(return_value="test@example.com"))

    asyncio.run(async_name_after_account(hass, entry, client))

    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, title="test@example.com"
    )


def test_name_after_account_renamed_meanwhile() -> None:
    """Keep a name the user chose while the email address was being looked up."""
    hass = Mock()
    entry = make_entry({"username": ""}, title=MASTER_TOKEN_TITLE)

    async def rename_during_lookup() -> str:
        entry.title = "Home speakers"
        return "test@example.com"

    client = Mock(async_get_email=AsyncMock(side_effect=rename_during_lookup))

    asyncio.run(async_name_after_account(hass, entry, client))

    hass.config_entries.async_update_entry.assert_not_called()


def test_name_after_account_without_email() -> None:
    """Leave the entry unchanged when Google doesn't give the email address."""
    hass = Mock()
    entry = make_entry({"username": ""}, title=MASTER_TOKEN_TITLE)
    client = Mock(async_get_email=AsyncMock(return_value=None))

    asyncio.run(async_name_after_account(hass, entry, client))

    hass.config_entries.async_update_entry.assert_not_called()


@pytest.fixture(name="hass")
def fixture_hass() -> Mock:
    """Return a fake Home Assistant whose entry Google returned two devices for."""
    online = GoogleHomeDevice(
        device_id="online", name="Kitchen", auth_token="token", ip_address="10.0.0.2"
    )
    offline = GoogleHomeDevice(device_id="offline", name="Bedroom", auth_token="token")
    offline.available = False
    hass = Mock()
    hass.data = {
        DOMAIN: {
            "entry": {
                DATA_CLIENT: Mock(google_devices_fetched=True),
                DATA_COORDINATOR: Mock(data=[online, offline]),
            }
        }
    }
    return hass


def can_delete(hass: Mock, device_id: str) -> bool:
    """Ask the integration whether the device with this ID can be deleted."""
    entry = Mock(entry_id="entry")
    device_entry = Mock(identifiers={(DOMAIN, device_id)})
    return asyncio.run(async_remove_config_entry_device(hass, entry, device_entry))


def test_keep_device_google_returns(hass: Mock) -> None:
    """Keep a device Google still returns."""
    assert not can_delete(hass, "online")


def test_keep_unavailable_device_google_returns(hass: Mock) -> None:
    """Keep an unavailable device Google still returns: it comes back on reload."""
    assert not can_delete(hass, "offline")


def test_delete_device_google_no_longer_returns(hass: Mock) -> None:
    """Allow deleting a device Google no longer returns."""
    assert can_delete(hass, "removed")


def test_keep_devices_of_unloaded_entry() -> None:
    """Keep devices while the entry isn't loaded, as Google's list is unknown."""
    assert not can_delete(Mock(data={}), "removed")


def test_keep_devices_when_fetch_fails() -> None:
    """Keep devices when Google's device list couldn't be fetched."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    client = GlocaltokensApiClient(hass, Mock(), master_token=MASTER_TOKEN)

    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.get_access_token",
        return_value=None,
    ):
        devices = asyncio.run(client.get_google_devices())

    hass.data = {
        DOMAIN: {"entry": {DATA_CLIENT: client, DATA_COORDINATOR: Mock(data=devices)}}
    }
    assert devices == []
    assert not can_delete(hass, "online")
