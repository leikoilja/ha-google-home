"""Tests for the Google Home Do Not Disturb switch."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.switch import DoNotDisturbSwitch


def test_turn_on_writes_state() -> None:
    """Show the new setting right away instead of at the next update."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    client = Mock(update_do_not_disturb=AsyncMock())
    switch = DoNotDisturbSwitch(
        Mock(data=[device]), client, "device-id", "Kitchen", None
    )

    with patch.object(switch, "async_write_ha_state") as write_state:
        asyncio.run(switch.async_turn_on())

    client.update_do_not_disturb.assert_awaited_once_with(device=device, enable=True)
    write_state.assert_called_once_with()
