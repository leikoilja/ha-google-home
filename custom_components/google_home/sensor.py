"""Sensor platforms for Google Home"""
import logging

from homeassistant.const import STATE_OFF, STATE_ON

from .const import (
    DOMAIN,
    LABEL_ALARMS,
    LABEL_TIMERS,
    LOCAL_TIME_ISO,
    SUPPORTED_HARDWARE_LIST,
)
from .entity import (
    GoogleHomeAlarmEntity,
    GoogleHomeNextAlarmEntity,
    GoogleHomeNextTimerEntity,
    GoogleHomeTimersEntity,
    GoogleHomeTokenEntity,
)
from .utils import (
    format_alarm_information,
    format_timer_information,
    sort_list_by_firetime,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    for device in coordinator.data:
        sensors.append(
            GoogleHomeTokenSensor(
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
                    device.alarms,
                ),
                GoogleHomeNextAlarmSensor(
                    coordinator,
                    entry,
                    device.name,
                    device.alarms,
                ),
                GoogleHomeTimerSensor(
                    coordinator,
                    entry,
                    device.name,
                    device.timers,
                ),
                GoogleHomeNextTimerSensor(
                    coordinator,
                    entry,
                    device.name,
                    device.timers,
                ),

            ]
    async_add_devices(sensors)


class GoogleHomeSensorMixin:
    def get_device(self):
        """Return the device matched by name
        from the list of google devices in coordinator_data"""
        return next(
            (
                device
                for device in self.coordinator.data
                if device.name == self._name
            ),
            None,
        )


class GoogleHomeTokenSensor(GoogleHomeSensorMixin, GoogleHomeTokenEntity):
    """GoogleHome Sensor class."""

    def __init__(self, coordinator, entry, name, token):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

    @property
    def state(self):
        return self.get_device().token

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeAlarmSensor(GoogleHomeSensorMixin, GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name, alarms):
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
            "device": str(self.name),
            "integration": DOMAIN,
        }

    def _get_alarms_data(self):
        """Update alarms data extracting it from coordinator"""
        alarms = [
            format_alarm_information(alarm)
            for alarm in getattr(self.get_device(), LABEL_ALARMS)
        ]
        alarms = sort_list_by_firetime(alarms)
        return alarms


class GoogleHomeNextAlarmSensor(GoogleHomeSensorMixin, GoogleHomeNextAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name, alarms):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

    @property
    def state(self):
        alarms = self._get_alarm_data()
        # The first one will always be the closest one
        # as we have sorted the list in _get_alarm_data()
        return alarms[0][LOCAL_TIME_ISO] if alarms else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        alarms = self._get_alarm_data()
        attributes = (
            alarms[0]
            if len(alarms)
            else {}
            # Only list the attributes for one
        )
        attributes.update(
            {
                "device": str(self.name),
                "integration": DOMAIN,
            }
        )
        return attributes

    def _get_alarm_data(self):
        """Update alarms data extracting it from coordinator"""
        alarms = [
            format_alarm_information(alarm)
            for alarm in getattr(self.get_device(), LABEL_ALARMS)
        ]
        return sort_list_by_firetime(alarms)


class GoogleHomeTimerSensor(GoogleHomeSensorMixin, GoogleHomeTimersEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name, timers):
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
            "device": str(self.name),
            "integration": DOMAIN,
        }

    def _get_timers_data(self):
        """Update timers data extracting it from coordinator"""
        timers = [
            format_timer_information(timer)
            for timer in getattr(self.get_device(), LABEL_TIMERS)
        ]
        return sort_list_by_firetime(timers)


class GoogleHomeNextTimerSensor(GoogleHomeSensorMixin, GoogleHomeNextTimerEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, name, alarms):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = name

    @property
    def state(self):
        timers = self._get_timers_data()
        # The first one will always be the closest one
        # as we have sorted the list in _get_alarm_data()
        return timers[0][LOCAL_TIME_ISO] if timers else STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        timers = self._get_timers_data()
        attributes = (
            timers[0]
            if len(timers)
            else {}
            # Only list the attributes for one
        )
        attributes.update(
            {
                "device": str(self.name),
                "integration": DOMAIN,
            }
        )
        return attributes

    def _get_timers_data(self):
        """Update alarms data extracting it from coordinator"""
        timers = [
            format_timer_information(timer)
            for timer in getattr(self.get_device(), LABEL_TIMERS)
        ]
        return sort_list_by_firetime(timers)
