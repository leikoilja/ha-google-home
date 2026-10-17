"""Switch platform for Google Home."""

import logging
from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    ICON_DO_NOT_DISTURB,
    LABEL_DO_NOT_DISTURB,
)
from .entity import GoogleHomeBaseEntity, async_add_device_entities
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

    async_add_device_entities(
        entry, coordinator, client, async_add_devices, DoNotDisturbSwitch
    )
    return True


class DoNotDisturbSwitch(GoogleHomeBaseEntity, SwitchEntity):
    """Google Home Do Not Disturb switch."""

    _attr_icon = ICON_DO_NOT_DISTURB
    _attr_entity_category = EntityCategory.CONFIG

    @property
    @override
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_DO_NOT_DISTURB

    @property
    @override
    def is_on(self) -> bool:
        """Return true if Do Not Disturb Mode is on."""
        device = self.get_device()

        if device is None:
            return False

        return device.get_do_not_disturb()

    async def set_do_not_disturb(self, enable: bool) -> None:
        """Set Do Not Disturb mode."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        await self.client.update_do_not_disturb(device=device, enable=enable)
        # Other entities show this device's data too
        self.coordinator.async_update_listeners()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:  # type: ignore[explicit-any]
        """Turn the entity on."""
        await self.set_do_not_disturb(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:  # type: ignore[explicit-any]
        """Turn the entity off."""
        await self.set_do_not_disturb(False)
