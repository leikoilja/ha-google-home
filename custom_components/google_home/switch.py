"""Switch platform for Google Home"""
import logging
from typing import Any, Callable, Iterable, List

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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
    async_add_devices: Callable[[Iterable[SwitchEntity]], None],
) -> bool:
    """Setup switch platform."""
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    switch: List[SwitchEntity] = []
    for device in coordinator.data:
        if device.auth_token and device.available:
            switch.append(
                DoNotDisturbSwitch(
                    coordinator,
                    client,
                    device.name,
                )
            )

    if switch:
        async_add_devices(switch)

    return True


class DoNotDisturbSwitch(GoogleHomeBaseEntity, SwitchEntity):
    """Google Home Do Not Disturb switch."""

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_DO_NOT_DISTURB

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        return ICON_DO_NOT_DISTURB

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        device = self.get_device()

        if device is None:
            return False

        is_enabled = device.get_do_not_disturb_status()

        return is_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:  # type: ignore[misc]
        """Turn the entity on."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        await self.client.get_or_set_do_not_disturb(device=device, enable=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # type: ignore[misc]
        """Turn the entity off."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        await self.client.get_or_set_do_not_disturb(device=device, enable=False)
