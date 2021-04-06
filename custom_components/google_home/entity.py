"""Defines base entities for Google Home"""

from abc import ABC, abstractmethod
from typing import List, Optional

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import GlocaltokensApiClient
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER
from .models import GoogleHomeDevice
from .types import DeviceInfo


class GoogleHomeBaseEntity(CoordinatorEntity, ABC):
    """Base entity base for Google Home sensors"""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        client: GlocaltokensApiClient,
        device_name: str,
    ):
        super().__init__(coordinator)
        self.client = client
        self.device_name = device_name

    @property
    @abstractmethod
    def label(self) -> str:
        """Label to use for name and unique id."""
        ...

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {self.label}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{self.label}"

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "manufacturer": MANUFACTURER,
        }

    def get_device(self) -> Optional[GoogleHomeDevice]:
        """Return the device matched by device name
        from the list of google devices in coordinator_data"""
        matched_devices: List[GoogleHomeDevice] = [
            device
            for device in self.coordinator.data
            if device.name == self.device_name
        ]
        return matched_devices[0] if matched_devices else None
