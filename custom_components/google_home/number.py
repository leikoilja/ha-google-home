"""Number Platform for Google Home."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    ICON_ALARM_VOLUME_HIGH,
    ICON_ALARM_VOLUME_LOW,
    ICON_ALARM_VOLUME_MID,
    ICON_ALARM_VOLUME_OFF,
    LABEL_ALARM_VOLUME,
)
from .entity import GoogleHomeBaseEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .api import GlocaltokensApiClient
    from .models import GoogleHomeDevice
    from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up switch platform."""
    client: GlocaltokensApiClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]

    numbers = [
        AlarmVolumeNumber(
            coordinator, client, device.device_id, device.name, device.hardware
        )
        for device in coordinator.data
        if device.auth_token and device.available
    ]

    if numbers:
        async_add_devices(numbers)

    return True


class AlarmVolumeNumber(GoogleHomeBaseEntity, NumberEntity):
    """Google Home Alarm Volume Number entity."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_ALARM_VOLUME

    @property
    def icon(self) -> str:  # type: ignore[override]
        """Return the icon of the sensor."""
        device = self.get_device()
        if device is None:
            return ICON_ALARM_VOLUME_OFF
        volume = device.get_alarm_volume()
        if volume == 0:
            return ICON_ALARM_VOLUME_OFF
        if volume <= 30:
            return ICON_ALARM_VOLUME_LOW
        if volume <= 60:
            return ICON_ALARM_VOLUME_MID
        return ICON_ALARM_VOLUME_HIGH

    @property
    def native_value(self) -> float:  # type: ignore[override]
        """Return the current volume value."""
        device = self.get_device()

        if device is None:
            return GOOGLE_HOME_ALARM_DEFAULT_VALUE

        return device.get_alarm_volume()

    async def async_set_native_value(self, value: float) -> None:
        """Set the alarm volume."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            return

        await self.client.update_alarm_volume(device=device, volume=round(value))
