"""Number Platform for Google Home"""

import logging
from typing import Callable, Iterable, List

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from const import (
    DOMAIN,
    DEVICE_CLASS_ALARM_VOLUME,
    DATA_CLIENT,
    DATA_COORDINATOR,
    LABEL_ALARM_VOLUME,
    ICON_ALARM_VOLUME_OFF,
    ICON_ALARM_VOLUME_LOW,
    ICON_ALARM_VOLUME_MID,
    ICON_ALARM_VOLUME_HIGH,
)
from .models import GOOGLE_HOME_ALARM_DEFAULT_VALUE
from .types import AlarmVolumeAttributes
from .entity import GoogleHomeBaseEntity

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: Callable[[Iterable[NumberEntity]], None],
) -> bool:
    """Setup switch platform."""
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    numbers: List[NumberEntity] = []
    for device in coordinator.data:
        if device.auth_token and device.available:
            numbers.append(
                AlarmVolumeNumber(
                    coordinator,
                    client,
                    device.name,
                )
            )

    if numbers:
        async_add_devices(numbers)

    return True


class AlarmVolumeNumber(GoogleHomeBaseEntity, NumberEntity):
    """Google Home Alarm Volume Number entity."""

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_ALARM_VOLUME

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        device = self.get_device()
        if device is None:
            return ICON_ALARM_VOLUME_HIGH
        volume = device.get_alarm_volume()
        if volume == 0:
            return ICON_ALARM_VOLUME_OFF
        elif volume <= 0.3:
            return ICON_ALARM_VOLUME_LOW
        elif volume <= 0.6:
            return ICON_ALARM_VOLUME_MID
        else:
            return ICON_ALARM_VOLUME_HIGH

    @property
    def min_value(self) -> float:
        """Return the minimum value for the volume"""
        return 0

    @property
    def max_value(self) -> float:
        """Return the minimum value for the volume"""
        return 1

    @property
    def step(self) -> float:
        """Return the step value for the volume"""
        return .01

    @property
    def value(self) -> float:
        """Return the current volume value"""
        device = self.get_device()

        if device is None:
            return GOOGLE_HOME_ALARM_DEFAULT_VALUE

        volume = device.get_alarm_volume()
        return volume

    @property
    def device_state_attributes(self) -> AlarmVolumeAttributes:
        """Return the state attributes."""
        return {
            "device_class": DEVICE_CLASS_ALARM_VOLUME,
            "integration": DOMAIN,
        }

    async def async_set_value(self, value: float) -> None:
        """Sets the alarm volume"""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.update_alarm_volume(device=device, volume=value)
