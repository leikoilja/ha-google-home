"""Tests for the Google Home Do Not Disturb switch."""

import asyncio
from unittest.mock import AsyncMock, Mock

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.switch import DoNotDisturbSwitch


def test_turn_on_updates_entities() -> None:
    """Show the new setting on every entity as soon as the device answers."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    coordinator = Mock(data=[device])
    client = Mock(
        update_do_not_disturb=AsyncMock(
            side_effect=lambda device, enable: device.set_do_not_disturb(enable)
        )
    )
    switch = DoNotDisturbSwitch(coordinator, client, "device-id", "Kitchen", None)
    shown: list[bool] = []
    coordinator.async_update_listeners.side_effect = lambda: shown.append(switch.is_on)

    asyncio.run(switch.async_turn_on())

    assert shown == [True]
