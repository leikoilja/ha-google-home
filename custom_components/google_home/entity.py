"""Defines base entities for Google Home."""

from abc import ABC, abstractmethod
from functools import partial
import logging
from typing import override

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GlocaltokensApiClient
from .const import DOMAIN, MANUFACTURER, UNANSWERED_UPDATES
from .coordinator import GoogleHomeDeviceCoordinator
from .exceptions import DeviceRequestFailed
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeBaseEntity(CoordinatorEntity[GoogleHomeDeviceCoordinator], ABC):
    """Base entity base for Google Home sensors."""

    # Subclasses name only themselves, and Home Assistant adds the device's
    # current name. So entities added after the user renames the device in
    # Home Assistant use its new name, not its Google Home name.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GoogleHomeDeviceCoordinator,
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
        """Label to use for unique id."""

    @property
    @override
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_id}/{self.label}"

    @property
    @override
    def available(self) -> bool:
        """Return whether Google still lists the device and it answers."""
        device = self.get_device()
        return (
            super().available
            and device is not None
            and device.unanswered_updates < UNANSWERED_UPDATES
        )

    @property
    @override
    def device_info(self) -> DeviceInfo | None:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
            model=self.device_model,
        )

    def get_device(self) -> GoogleHomeDevice | None:
        """Return the entity's device, if Google lists it."""
        return self.coordinator.data

    @callback
    def async_show_device_changes(self) -> None:
        """Show a change to the device's data now, on each of its entities."""
        # The device's other entities show its data too
        self.coordinator.async_update_listeners()

    async def async_reboot_device(self) -> None:
        """Reboot the device."""
        device = self.get_device()

        if device is None:
            _LOGGER.error("Device %s is not found.", self.device_name)
            raise DeviceRequestFailed(self.device_name, "request_failed")

        await self.client.reboot_google_device(device)


class GoogleHomeFeatureEntity(GoogleHomeBaseEntity):
    """Base entity for alarms, timers and their settings, which some devices don't have."""

    @property
    @override
    def available(self) -> bool:
        """Return whether Google still lists the device, it answers and it has these features."""
        device = self.get_device()
        return (
            super().available and device is not None and not device.alarms_unsupported
        )


def async_add_device_entities(
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
    *entity_classes: type[GoogleHomeBaseEntity],
    needs_answer: bool = True,
) -> None:
    """Add these entities for each device, at setup or when a later update finds it.

    With needs_answer, a device gets them only once it answers: one that is
    offline or doesn't support alarms, timers and settings gets none. Each device's
    coordinator is watched from when the account's coordinator adds it, which also
    keeps it updating before the device has entities.
    """
    client = entry.runtime_data.client
    added: set[str] = set()
    watched: set[str] = set()

    @callback
    def add_entities(coordinator: GoogleHomeDeviceCoordinator) -> None:
        device = coordinator.data
        if (
            device is None
            or device.device_id in added
            or (
                needs_answer
                and not (
                    device.auth_token
                    and device.available
                    and not device.alarms_unsupported
                )
            )
        ):
            return
        added.add(device.device_id)
        async_add_entities(
            [
                entity_class(
                    coordinator, client, device.device_id, device.name, device.hardware
                )
                for entity_class in entity_classes
            ]
        )

    @callback
    def watch_devices() -> None:
        for device_id, coordinator in entry.runtime_data.devices.items():
            if device_id in watched:
                continue
            watched.add(device_id)
            # Its first update may have finished already
            add_entities(coordinator)
            entry.async_on_unload(
                coordinator.async_add_listener(partial(add_entities, coordinator))
            )

    watch_devices()
    entry.async_on_unload(entry.runtime_data.account.async_add_listener(watch_devices))
