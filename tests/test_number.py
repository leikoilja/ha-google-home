"""Tests for the Google Home alarm volume number."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber


def test_set_value_writes_state() -> None:
    """Show the new volume right away instead of at the next update."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    client = Mock(update_alarm_volume=AsyncMock())
    number = AlarmVolumeNumber(
        Mock(data=[device]), client, "device-id", "Kitchen", None
    )

    with patch.object(number, "async_write_ha_state") as write_state:
        asyncio.run(number.async_set_native_value(40.4))

    client.update_alarm_volume.assert_awaited_once_with(device=device, volume=40)
    write_state.assert_called_once_with()
