"""Sensor platforms for Google Home"""

import logging

from homeassistant.const import STATE_OFF
from homeassistant.const import STATE_ON

from .const import DOMAIN
from .const import FIRE_TIME_IN_S
from .const import LABEL_ALARMS
from .const import LABEL_TIMERS
from .const import LABEL_TOKEN
from .entity import GoogleHomeAlarmEntity
from .entity import GoogleHomeTokenEntity
from .entity import GoogleHomeTimersEntity
from .utils import format_alarm_information
from .utils import format_timer_information


_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for device_name, device_data in coordinator.data.items():
        devices_to_add = []
        if device_data[LABEL_TOKEN]:
            devices_to_add.append(
                GoogleHomeTokenSensor(coordinator, entry, device_name, device_data)
            )
        if device_data[LABEL_ALARMS]:
            devices_to_add.append(
                GoogleHomeAlarmSensor(coordinator, entry, device_name, device_data)
            )
        if device_data[LABEL_TIMERS]:
            devices_to_add.append(
                GoogleHomeTimerSensor(coordinator, entry, device_name, device_data)
            )
        if devices_to_add:
            async_add_devices(devices_to_add)


class GoogleHomeTokenSensor(GoogleHomeTokenEntity):
    """GoogleHome Sensor class."""

    def __init__(self, coordinator, entry, device_name, device_data):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name
        self._state = device_data[LABEL_TOKEN]

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeAlarmSensor(GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device_name, device_data):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name
        self._alarms_timestamp = device_data[LABEL_ALARMS]
        self._alarms = [format_alarm_information(alarm) for alarm in device_data[LABEL_ALARMS]]

        if len(self._alarms) > 0:
            self._state = self._alarms[0][FIRE_TIME_IN_S]
        else:
            self._state = STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        _LOGGER.debug('ALARM ATTRIBUTE data', self.coordinator.data)
        return {
            "device data": self.coordinator.data[self._name],
            "alarms": self._alarms,
            "alarms timestamps": self._alarms_timestamp,
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeTimerSensor(GoogleHomeTimersEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device_name, device_data):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name
        self._timers_timestamp = device_data[LABEL_TIMERS]
        self._timers = [format_timer_information(timer) for timer in device_data[LABEL_TIMERS]]

        if len(self._timers) > 0:
            self._state = STATE_ON
        else:
            self._state = STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "timers": self._timers,
            "timers timestamps": self._timers_timestamp,
            "device": str(self.name),
            "integration": DOMAIN,
        }
