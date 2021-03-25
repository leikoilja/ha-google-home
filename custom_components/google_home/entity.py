"""Defines base entities for Google Home"""

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


class GoogleHomeBaseEntity(CoordinatorEntity):
    """Base entity base for Google Home sensors"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
        self.device_name = device_name

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
        return next(
            (
                device
                for device in self.coordinator.data
                if device.name == self.device_name
            ),
            None,
        )

    @staticmethod
    def as_dict(obj_list: List[Any]) -> List[Dict[Any, Any]]:
        """Return list of objects represented as dictionaries """
        return [obj.__dict__ for obj in obj_list]
