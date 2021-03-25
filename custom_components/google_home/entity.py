"""Defines base entities for Google Home"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set, Tuple, TypedDict

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER


class DeviceInfo(TypedDict):
    """Typed dict for device_info"""

    identifiers: Set[Tuple[str, str]]
    name: str
    manufacturer: str


class GoogleHomeBaseEntity(CoordinatorEntity, ABC):
    """Base entity base for Google Home sensors"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
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

    def get_device(self):
        """Return the device matched by device name
        from the list of google devices in coordinator_data"""
        matched_devices = [
            device
            for device in self.coordinator.data
            if device.name == self.device_name
        ]
        return matched_devices[0] if matched_devices else None

    @staticmethod
    def as_dict(obj_list: List[Any]) -> List[Dict[Any, Any]]:
        """Return list of objects represented as dictionaries """
        return [obj.__dict__ for obj in obj_list]
