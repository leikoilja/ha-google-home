"""Tests for the Google Home Reboot button."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.google_home.button import RebootButton
from custom_components.google_home.models import GoogleHomeDevice


def test_press_reboots_device() -> None:
    """Pressing the button reboots the device it belongs to."""
    kitchen = GoogleHomeDevice("kitchen-id", "Kitchen", "token")
    coordinator = Mock(
        data=[GoogleHomeDevice("bedroom-id", "Bedroom", "token"), kitchen]
    )
    client = Mock(reboot_google_device=AsyncMock())
    button = RebootButton(coordinator, client, "kitchen-id", "Kitchen", None)

    asyncio.run(button.async_press())

    client.reboot_google_device.assert_awaited_once_with(kitchen)


@pytest.mark.parametrize(
    ("ip_address", "listed", "available"),
    [("192.168.1.10", True, True), (None, True, False), ("192.168.1.10", False, False)],
)
def test_button_available(
    ip_address: str | None, listed: bool, available: bool
) -> None:
    """Grey out the button for a device that isn't found or has no IP address."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token", ip_address=ip_address)
    coordinator = Mock(data=[device] if listed else [], last_update_success=True)
    button = RebootButton(coordinator, Mock(), "device-id", "Kitchen", None)

    assert button.available is available
