"""Switch platform for Google Home."""

import logging
from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ICON_DO_NOT_DISTURB, LABEL_DO_NOT_DISTURB
from .entity import GoogleHomeFeatureEntity, async_add_device_entities
from .exceptions import DeviceRequestFailed
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)

# The coordinator does the updates. A limit on actions would count every
# speaker's switch together, so it would make speakers wait for each other.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up switch platform."""
    async_add_device_entities(entry, async_add_devices, DoNotDisturbSwitch)
    return True


class DoNotDisturbSwitch(GoogleHomeFeatureEntity, SwitchEntity):
    """Google Home Do Not Disturb switch."""

    _attr_translation_key = "do_not_disturb"
    _attr_icon = ICON_DO_NOT_DISTURB
    _attr_entity_category = EntityCategory.CONFIG

    @property
    @override
    def label(self) -> str:
        """Label to use for unique id."""
        return LABEL_DO_NOT_DISTURB

    @property
    @override
    def is_on(self) -> bool:
        """Return true if Do Not Disturb Mode is on."""
        device = self.get_device()

        if device is None:
            return False

        return device.do_not_disturb

    async def set_do_not_disturb(self, enable: bool) -> None:
        """Set Do Not Disturb mode."""
        device = self.get_device()
        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            raise DeviceRequestFailed(self.device_name, "request_failed")

        await self.client.set_do_not_disturb(device=device, enable=enable)
        self.async_show_device_changes()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:  # type: ignore[explicit-any]
        """Turn the entity on."""
        await self.set_do_not_disturb(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:  # type: ignore[explicit-any]
        """Turn the entity off."""
        await self.set_do_not_disturb(False)
