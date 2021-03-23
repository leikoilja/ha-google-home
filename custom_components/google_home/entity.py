"""Defines base entities for Google Home"""

from typing import Set, Tuple, TypedDict

from homeassistant.const import DEVICE_CLASS_TIMESTAMP
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DEFAULT_NAME,
    DOMAIN,
    ICON_ALARMS,
    ICON_TIMERS,
    ICON_TOKEN,
    LABEL_ALARMS,
    LABEL_DEVICE,
    LABEL_NEXT_ALARM,
    LABEL_NEXT_TIMER,
    LABEL_TIMERS,
    MANUFACTURER,
    VERSION,
)


class DeviceInfo(TypedDict):
    """Typed dict for device_info"""

    identifiers: Set[Tuple[str, str]]
    name: str
    model: str
    manufacturer: str


class GoogleHomeDeviceEntity(CoordinatorEntity):
    """Entity base for device sensor"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_DEVICE}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_DEVICE}"

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        return ICON_TOKEN

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return "google_home__custom_device_class"


class GoogleHomeAlarmEntity(CoordinatorEntity):
    """Entity base for Alarm sensor"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_ALARMS}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_ALARMS}"

    @property
    def icon(self) -> str:
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS


class GoogleHomeNextAlarmEntity(CoordinatorEntity):
    """Entity base for next alarm sensor"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_NEXT_ALARM}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_NEXT_ALARM}"

    @property
    def icon(self) -> str:
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return DEVICE_CLASS_TIMESTAMP


class GoogleHomeTimersEntity(CoordinatorEntity):
    """Entity base for timers sensor"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_TIMERS}"

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_TIMERS}"

    @property
    def icon(self) -> str:
        """Icon to use in the frontend, if any."""
        return ICON_TIMERS


class GoogleHomeNextTimerEntity(CoordinatorEntity):
    """Entity base for next timer sensor"""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str):
        super().__init__(coordinator)
        self.device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": f"{DEFAULT_NAME} {self.device_name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} {LABEL_NEXT_TIMER}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{self.device_name}/{LABEL_NEXT_TIMER}"

    @property
    def icon(self) -> str:
        """Icon to use in the frontend, if any."""
        return ICON_TIMERS

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return DEVICE_CLASS_TIMESTAMP
