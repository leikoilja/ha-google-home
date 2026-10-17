"""Defines base entities for Google Home."""

from abc import ABC, abstractmethod
import logging
from typing import override

from homeassistant.core import ServiceCall, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import GlocaltokensApiClient
from .const import DOMAIN, MANUFACTURER
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeBaseEntity(
    CoordinatorEntity[DataUpdateCoordinator[list[GoogleHomeDevice]]], ABC
):
    """Base entity base for Google Home sensors."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]],
        client: GlocaltokensApiClient,
        device_id: str,
        device_name: str,
        device_model: str | None,
    ):
        """Create Google Home base entity."""
        super().__init__(coordinator)
        self.client = client
        self.device_id = device_id
        self.device_name = device_name
        self.device_model = device_model

    @property
    @abstractmethod
    def label(self) -> str:
        """Label to use for name and unique id."""

    @property
    @override
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {self.label}"

    @property
    @override
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_id}/{self.label}"

    @property
    @override
    def device_info(self) -> DeviceInfo | None:
        """Return device info."""
        # Entity names start with the device name, which Home Assistant strips
        # when it builds entity IDs from both: sensor.kitchen_alarms, not
        # sensor.google_home_kitchen_kitchen_alarms.
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
            model=self.device_model,
        )

    def get_device(self) -> GoogleHomeDevice | None:
        """Return the device matched by device name from the list of google devices in coordinator_data."""
        matched_devices: list[GoogleHomeDevice] = [
            device
            for device in self.coordinator.data
            if device.device_id == self.device_id
        ]
        return matched_devices[0] if matched_devices else None

    async def async_reboot_device(self, _call: ServiceCall | None = None) -> None:
        """Reboot the device."""
        device = self.get_device()

        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            return

        await self.client.reboot_google_device(device)


def async_add_device_entities(
    entry: GoogleHomeConfigEntry,
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]],
    client: GlocaltokensApiClient,
    async_add_entities: AddEntitiesCallback,
    *entity_classes: type[GoogleHomeBaseEntity],
    needs_answer: bool = True,
) -> None:
    """Add these entities for each device, at setup or when a later update finds it.

    With needs_answer, a device gets them only once it answers: one that is
    offline or doesn't support alarms, timers and settings gets none.
    """
    added: set[str] = set()

    @callback
    def add_entities() -> None:
        devices = [
            device
            for device in coordinator.data
            if device.device_id not in added
            and (not needs_answer or (device.auth_token and device.available))
        ]
        if not devices:
            return
        added.update(device.device_id for device in devices)
        async_add_entities(
            [
                entity_class(
                    coordinator, client, device.device_id, device.name, device.hardware
                )
                for device in devices
                for entity_class in entity_classes
            ]
        )

    add_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_entities))
