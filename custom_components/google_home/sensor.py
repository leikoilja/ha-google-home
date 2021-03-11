"""Sensor platforms for Google Home"""
import logging

from homeassistant.const import STATE_OFF, STATE_ON

from .const import DOMAIN
from .entity import (
    GoogleHomeAlarmEntity,
    GoogleHomeDeviceEntity,
    GoogleHomeNextAlarmEntity,
    GoogleHomeNextTimerEntity,
    GoogleHomeTimersEntity,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    for device in coordinator.data:
        sensors.append(
            GoogleHomeDeviceSensor(
                coordinator,
                device.name,
                device.auth_token,
            )
        )
        if device.auth_token and device.available:
            sensors += [
                GoogleHomeAlarmSensor(
                    coordinator,
                    device.name,
                ),
                GoogleHomeNextAlarmSensor(
                    coordinator,
                    device.name,
                ),
                GoogleHomeTimerSensor(
                    coordinator,
                    device.name,
                ),
                GoogleHomeNextTimerSensor(
                    coordinator,
                    device.name,
                ),
            ]
    async_add_devices(sensors)


class GoogleHomeSensorMixin:
    """Adds basic functions to sensors"""
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
    def as_dict(obj_list):
        """Return list of objects represented as dictionaries """
        return [obj.__dict__ for obj in obj_list]


class GoogleHomeDeviceSensor(GoogleHomeSensorMixin, GoogleHomeDeviceEntity):
    """GoogleHome Device Sensor class."""

    def __init__(self, coordinator, device_name, auth_token):
        """Initialize the sensor."""
        super().__init__(coordinator, device_name)
        self.auth_token = auth_token

    @property
    def state(self):
        device = self.get_device()
        auth_token = device.auth_token if device else self.auth_token
        return auth_token

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
        attributes = self.get_device_attributes(device) if device else attributes
        return attributes

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


class GoogleHomeAlarmSensor(GoogleHomeSensorMixin, GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    @property
    def state(self):
        alarms = self._get_alarms_data()
        state = STATE_ON if len(alarms) else STATE_OFF
        return state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "alarms": self._get_alarms_data(),
            "integration": DOMAIN,
        }

    def _get_alarms_data(self):
        """Update alarms data extracting it from coordinator"""
        device = self.get_device()
        return self.as_dict(device.get_sorted_alarms())


class GoogleHomeNextAlarmSensor(GoogleHomeSensorMixin, GoogleHomeNextAlarmEntity):
    """Representation of a Sensor."""

    @property
    def state(self):
        alarm = self._get_next_alarm()
        return alarm.local_time_iso if alarm else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        alarm = self._get_next_alarm()
        attributes = alarm.__dict__ if alarm else {}
        attributes.update(
            {
                "integration": DOMAIN,
            }
        )
        return attributes

    def _get_next_alarm(self):
        """Update alarms data extracting it from coordinator"""
        device = self.get_device()
        alarm = device.get_next_alarm()
        return alarm


class GoogleHomeTimerSensor(GoogleHomeSensorMixin, GoogleHomeTimersEntity):
    """Representation of a Sensor."""

    @property
    def state(self):
        timers = self._get_timers_data()
        return STATE_ON if len(timers) else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "timers": self._get_timers_data(),
            "integration": DOMAIN,
        }

    def _get_timers_data(self):
        """Update timers data extracting it from coordinator"""
        device = self.get_device()
        return self.as_dict(device.get_sorted_timers())


class GoogleHomeNextTimerSensor(GoogleHomeSensorMixin, GoogleHomeNextTimerEntity):
    """Representation of a Sensor."""

    @property
    def state(self):
        timer = self._get_next_timer()
        return timer.local_time_iso if timer else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        timer = self._get_next_timer()
        attributes = timer.__dict__ if timer else {}
        attributes.update(
            {
                "integration": DOMAIN,
            }
        )
        return attributes

    def _get_next_timer(self):
        """Update alarms data extracting it from coordinator"""
        device = self.get_device()
        timer = device.get_next_timer()
        return timer
