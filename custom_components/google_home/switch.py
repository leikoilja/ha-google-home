"""Switch platform for Google Home"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    ICON_DO_NOT_DISTURB,
    LABEL_DO_NOT_DISTURB,
)
from .entity import GoogleHomeBaseEntity

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Setup switch platform."""
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    switches: list[SwitchEntity] = []
    for device in coordinator.data:
        if device.auth_token and device.available:
            switches.append(
                DoNotDisturbSwitch(
                    coordinator,
                    client,
                    device.device_id,
                    device.name,
                    device.hardware,
                )
            )

    if switches:
        async_add_devices(switches)

    return True


class DoNotDisturbSwitch(GoogleHomeBaseEntity, SwitchEntity):
    """Google Home Do Not Disturb switch."""

    _attr_icon = ICON_DO_NOT_DISTURB
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_DO_NOT_DISTURB

    @property
    def is_on(self) -> bool:
        """Return true if Do Not Disturb Mode is on."""
        device = self.get_device()

        if device is None:
            return False

        is_enabled = device.get_do_not_disturb()

        return is_enabled

    async def set_do_not_disturb(self, enable: bool) -> None:
        """Sets Do Not Disturb mode."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        await self.client.update_do_not_disturb(device=device, enable=enable)

    async def async_turn_on(self, **kwargs: Any) -> None:  # type: ignore[misc]
        """Turn the entity on."""
        await self.set_do_not_disturb(True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # type: ignore[misc]
        """Turn the entity off."""
        await self.set_do_not_disturb(False)
