"""Tests for the Google Home alarm volume number."""

import asyncio
from unittest.mock import AsyncMock, Mock

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber


def test_set_value_updates_entities() -> None:
    """Show the new volume on every entity as soon as the device answers."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    coordinator = Mock(data=[device])
    client = Mock(
        update_alarm_volume=AsyncMock(
            side_effect=lambda device, volume: device.set_alarm_volume(volume)
        )
    )
    number = AlarmVolumeNumber(coordinator, client, "device-id", "Kitchen", None)
    shown: list[float] = []
    coordinator.async_update_listeners.side_effect = lambda: shown.append(
        number.native_value
    )

    asyncio.run(number.async_set_native_value(40.4))

    assert shown == [40]
