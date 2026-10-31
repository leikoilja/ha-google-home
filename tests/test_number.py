"""Tests for the Google Home alarm volume number."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber


@pytest.mark.parametrize(
    ("volume", "icon"),
    [
        (0, "mdi:volume-off"),
        (1, "mdi:volume-low"),
        (30, "mdi:volume-low"),
        (31, "mdi:volume-medium"),
        (60, "mdi:volume-medium"),
        (61, "mdi:volume-high"),
    ],
)
def test_icon_follows_volume(volume: int, icon: str) -> None:
    """Show the alarm volume as off at 0%, low up to 30%, medium up to 60% and high above."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    device.alarm_volume = volume
    number = AlarmVolumeNumber(Mock(data=device), Mock(), "device-id", "Kitchen", None)

    assert number.icon == icon


def test_set_value_updates_entities() -> None:
    """Show the new volume on the device's entities as soon as it answers."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    coordinator = Mock(data=device)
    client = Mock(
        set_alarm_volume=AsyncMock(
            side_effect=lambda device, volume: setattr(device, "alarm_volume", volume)
        )
    )
    number = AlarmVolumeNumber(coordinator, client, "device-id", "Kitchen", None)
    shown: list[float] = []
    coordinator.async_update_listeners.side_effect = lambda: shown.append(
        number.native_value
    )

    asyncio.run(number.async_set_native_value(40.4))

    assert shown == [40]
