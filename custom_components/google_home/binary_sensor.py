"""Binary sensor platform for Google Home."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LABEL_FIRMWARE_UPDATE
from .entity import GoogleHomeBaseEntity, async_add_device_entities
from .types import GoogleHomeConfigEntry

# The coordinator does the updates, and the sensor has no actions
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up binary sensor platform."""
    # Devices without alarms have firmware too
    async_add_device_entities(
        entry, async_add_devices, FirmwareUpdateBinarySensor, needs_answer=False
    )
    return True


class FirmwareUpdateBinarySensor(GoogleHomeBaseEntity, BinarySensorEntity):
    """Whether the device says that a firmware update is waiting to be installed.

    Only the device's own flag: nothing compares its version with Google's. Without a
    translation key, Home Assistant names it after its device class, in its language.
    """

    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_FIRMWARE_UPDATE

    @property
    @override
    def available(self) -> bool:
        """Return whether the device was found on the network, as for its device sensor."""
        device = self.get_device()
        return (
            super().available and device is not None and device.ip_address is not None
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether an update is waiting, or None until the device says."""
        device = self.get_device()
        return device.has_update if device else None
