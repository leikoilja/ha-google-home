"""Button platform for Google Home."""

from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.components.button.const import ButtonDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import DATA_CLIENT, DATA_COORDINATOR, DOMAIN, LABEL_REBOOT
from .entity import GoogleHomeBaseEntity, async_add_device_entities
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> bool:
    """Set up button platform."""
    client: GlocaltokensApiClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]

    # Rebooting doesn't need alarms, so devices without them get a button too.
    async_add_device_entities(
        entry, coordinator, client, async_add_devices, RebootButton, needs_answer=False
    )
    return True


class RebootButton(GoogleHomeBaseEntity, ButtonEntity):
    """Google Home Reboot button."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    @property
    @override
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_REBOOT

    @property
    @override
    def available(self) -> bool:
        """Return whether the device can be asked to reboot."""
        device = self.get_device()
        return (
            super().available and device is not None and device.ip_address is not None
        )

    @override
    async def async_press(self) -> None:
        """Reboot the device."""
        await self.async_reboot_device()
