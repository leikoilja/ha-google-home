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
                entry,
                device.name,
                device.token,
            )
        )
        if device.token and device.available:
            sensors += [
                GoogleHomeAlarmSensor(
                    coordinator,
                    entry,
                    device.name,
                ),
                GoogleHomeNextAlarmSensor(
                    coordinator,
                    entry,
                    device.name,
                ),
                GoogleHomeTimerSensor(
                    coordinator,
                    entry,
                    device.name,
                ),
                GoogleHomeNextTimerSensor(
                    coordinator,
                    entry,
                    device.name,
                ),
            ]
    async_add_devices(sensors)


class GoogleHomeSensorMixin:
    def get_device(self):
        """Return the device matched by name
        from the list of google devices in coordinator_data"""
        return next(
            (device for device in self.coordinator.data if device.name == self._name),
            None,
        )


class GoogleHomeDeviceSensor(GoogleHomeSensorMixin, GoogleHomeDeviceEntity):
    """GoogleHome Device Sensor class."""

    def __init__(self, coordinator, entry, name, token):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name
        self.token = token
        device = self.get_device()
        self.initial_attributes = device.as_dict(device, flat=True)

    @property
    def state(self):
        device = self.get_device()
        token = device.token if device else self.token
        return token

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        device = self.get_device()
        attributes = (
            device.as_dict(device, flat=True) if device else self.initial_attributes
        )
        return attributes


class GoogleHomeAlarmSensor(GoogleHomeSensorMixin, GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

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
        return device.get_alarms_as_dict()


class GoogleHomeNextAlarmSensor(GoogleHomeSensorMixin, GoogleHomeNextAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

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

    def __init__(self, coordinator, entry, name):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

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
        return device.get_timers_as_dict()


class GoogleHomeNextTimerSensor(GoogleHomeSensorMixin, GoogleHomeNextTimerEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

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
