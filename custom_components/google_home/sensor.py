"""Sensor platforms for Google Home"""
import logging
from typing import Any, Dict, Iterable, List, Optional

from typing_extensions import Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEVICE_CLASS_TIMESTAMP, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    ICON_ALARMS,
    ICON_TIMERS,
    ICON_TOKEN,
    LABEL_ALARMS,
    LABEL_DEVICE,
    LABEL_TIMERS,
)
from .entity import GoogleHomeBaseEntity

_LOGGER: logging.Logger = logging.getLogger(__package__)


class AddEntitiesCallback(Protocol):
    """Protocol type for async_setup_entry callback"""

    def __call__(
        self, new_entities: Iterable[Entity], update_before_add: bool = False
    ) -> None:
        ...


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_devices: AddEntitiesCallback
) -> bool:
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    for device in coordinator.data:
        sensors.append(
            GoogleHomeDeviceSensor(
                coordinator,
                device.name,
            )
        )
        if device.auth_token and device.available:
            sensors += [
                GoogleHomeAlarmsSensor(
                    coordinator,
                    device.name,
                ),
                GoogleHomeTimersSensor(
                    coordinator,
                    device.name,
                ),
            ]
    async_add_devices(sensors)
    return True


class GoogleHomeDeviceSensor(GoogleHomeBaseEntity):
    """Google Home Device sensor."""

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_DEVICE

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        return ICON_TOKEN

    @property
    def state(self) -> Optional[str]:
        device = self.get_device()
        return device.auth_token if device else None

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        device = self.get_device()
        attributes = {
            "device_name": self.device_name,
            "auth_token": None,
            "ip_address": None,
            "hardware": None,
            "available": False,
            "integration": DOMAIN,
        }
        return self.get_device_attributes(device) if device else attributes

    @staticmethod
    def get_device_attributes(device):
        """Device representation as dictionary"""
        return {
            "device_name": device.name,
            "auth_token": device.auth_token,
            "ip_address": device.ip_address,
            "hardware": device.hardware,
            "available": device.available,
            "integration": DOMAIN,
        }


class GoogleHomeAlarmsSensor(GoogleHomeBaseEntity):
    """Google Home Alarms sensor."""

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_ALARMS

    @property
    def icon(self) -> str:
        """Icon to use in the frontend."""
        return ICON_ALARMS

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return DEVICE_CLASS_TIMESTAMP

    @property
    def state(self) -> Optional[str]:
        device = self.get_device()
        if not device:
            return None
        next_alarm = device.get_next_alarm()
        return next_alarm.local_time_iso if next_alarm else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "alarms": self._get_alarms_data(),
            "integration": DOMAIN,
        }

    def _get_alarms_data(self) -> List[Dict[Any, Any]]:
        """Update alarms data extracting it from coordinator"""
        device = self.get_device()
        return self.as_dict(device.get_sorted_alarms()) if device else []


class GoogleHomeTimersSensor(GoogleHomeBaseEntity):
    """Google Home Timers sensor."""

    @property
    def label(self) -> str:
        """Label to use for name and unique id."""
        return LABEL_TIMERS

    @property
    def icon(self) -> str:
        """Icon to use in the frontend."""
        return ICON_TIMERS

    @property
    def device_class(self) -> str:
        """Return the device class of the sensor."""
        return DEVICE_CLASS_TIMESTAMP

    @property
    def state(self) -> Optional[str]:
        device = self.get_device()
        if not device:
            return None
        timer = device.get_next_timer()
        return timer.local_time_iso if timer else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "timers": self._get_timers_data(),
            "integration": DOMAIN,
        }

    def _get_timers_data(self) -> List[Dict[Any, Any]]:
        """Update timers data extracting it from coordinator"""
        device = self.get_device()
        return self.as_dict(device.get_sorted_timers()) if device else []
