"""Number Platform for Google Home."""

import logging
from typing import override

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory, UnitOfRatio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    GOOGLE_HOME_ALARM_DEFAULT_VALUE,
    ICON_ALARM_VOLUME_HIGH,
    ICON_ALARM_VOLUME_LOW,
    ICON_ALARM_VOLUME_MID,
    ICON_ALARM_VOLUME_OFF,
    LABEL_ALARM_VOLUME,
)
from .entity import GoogleHomeFeatureEntity, async_add_device_entities
from .exceptions import DeviceRequestFailed
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)

# The coordinator does the updates. A limit on actions would count every
# speaker's alarm volume together, so it would make speakers wait for each other.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up switch platform."""
    async_add_device_entities(entry, async_add_devices, AlarmVolumeNumber)
    return True


class AlarmVolumeNumber(GoogleHomeFeatureEntity, NumberEntity):
    """Google Home Alarm Volume Number entity."""

    _attr_name = "Alarm volume"
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_ALARM_VOLUME

    @property
    @override
    def icon(self) -> str:
        """Return the icon of the sensor."""
        device = self.get_device()
        if device is None:
            return ICON_ALARM_VOLUME_OFF
        volume = device.alarm_volume
        if volume == 0:
            return ICON_ALARM_VOLUME_OFF
        if volume <= 30:
            return ICON_ALARM_VOLUME_LOW
        if volume <= 60:
            return ICON_ALARM_VOLUME_MID
        return ICON_ALARM_VOLUME_HIGH

    @property
    @override
    def native_value(self) -> float:
        """Return the current volume value."""
        device = self.get_device()

        if device is None:
            return GOOGLE_HOME_ALARM_DEFAULT_VALUE

        return device.alarm_volume

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the alarm volume."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s not found.", self.device_name)
            raise DeviceRequestFailed(self.device_name, "request_failed")

        await self.client.set_alarm_volume(device=device, volume=round(value))
        self.async_show_device_changes()
