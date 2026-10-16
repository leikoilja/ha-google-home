"""Defines base entities for Google Home."""

from abc import ABC, abstractmethod
from typing import override

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import GlocaltokensApiClient
from .const import DOMAIN, MANUFACTURER
from .models import GoogleHomeDevice


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
