"""Sensor platforms for Google Home"""
import logging

from homeassistant.const import STATE_OFF

from .const import DOMAIN
from .const import LABEL_ALARMS
from .const import LABEL_TIMERS
from .const import LABEL_TOKEN
from .const import LOCAL_TIME
from .const import TIME_LEFT
from .entity import GoogleHomeAlarmEntity
from .entity import GoogleHomeTimersEntity
from .entity import GoogleHomeTokenEntity
from .utils import format_alarm_information
from .utils import format_timer_information


_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for device_name, device_data in coordinator.data.items():
        if device_data[LABEL_TOKEN]:
            async_add_devices(
                [
                    GoogleHomeAlarmSensor(
                        coordinator, entry, device_name, device_data[LABEL_ALARMS]
                    ),
                    GoogleHomeTimerSensor(
                        coordinator, entry, device_name, device_data[LABEL_TIMERS]
                    ),
                    GoogleHomeTokenSensor(
                        coordinator, entry, device_name, device_data[LABEL_TOKEN]
                    ),
                ]
            )


class GoogleHomeTokenSensor(GoogleHomeTokenEntity):
    """GoogleHome Sensor class."""

    def __init__(self, coordinator, entry, device_name, local_auth_token):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name
        self._state = local_auth_token

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeAlarmSensor(GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device_name, alarms):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

    @property
    def state(self):
        alarms = self.get_alarms_data()
        state = alarms[0][LOCAL_TIME] if alarms else STATE_OFF
        return state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "alarms": self.get_alarms_data(),
            "device": str(self.name),
            "integration": DOMAIN,
        }

    def get_alarms_data(self):
        """Update alarms data extracting it from coordinator"""
        alarms = [
            format_alarm_information(alarm)
            for alarm in self.coordinator.data[self._name][LABEL_ALARMS]
        ]
        return alarms


class GoogleHomeTimerSensor(GoogleHomeTimersEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device_name, timers):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

    @property
    def state(self):
        timers = self.get_timers_data()
        state = timers[0][TIME_LEFT] if timers else STATE_OFF
        return state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "timers": self.get_timers_data(),
            "device": str(self.name),
            "integration": DOMAIN,
        }

    def get_timers_data(self):
        """Update timers data extracting it from coordinator"""
        timers = [
            format_timer_information(timer)
            for timer in self.coordinator.data[self._name][LABEL_TIMERS]
        ]
        return timers
