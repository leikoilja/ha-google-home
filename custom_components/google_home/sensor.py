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
    for device in coordinator.data:
        if device.local_auth_token and getattr(device, LABEL_AVAILABLE, True):
            async_add_devices(
                [
                    GoogleHomeAlarmSensor(
                        coordinator,
                        entry,
                        device.device_name,
                        getattr(device, LABEL_ALARMS),
                    ),
                    GoogleHomeNextAlarmSensor(
                        coordinator,
                        entry,
                        device.device_name,
                        getattr(device, LABEL_ALARMS),
                    ),
                    GoogleHomeTimerSensor(
                        coordinator,
                        entry,
                        device.device_name,
                        getattr(device, LABEL_TIMERS),
                    ),
                    GoogleHomeNextTimerSensor(
                        coordinator,
                        entry,
                        device.device_name,
                        getattr(device, LABEL_TIMERS),
                    ),
                    GoogleHomeTokenSensor(
                        coordinator,
                        entry,
                        device.device_name,
                        device.local_auth_token,
                    ),
                ]
            )


class GoogleHomeSensorMixin:
    def get_device(self):
        """Return the device matched by name
        from the list of google devices in coordinator_data"""
        return next(
            (
                device
                for device in self.coordinator.data
                if device.device_name == self._name
            ),
            None,
        )


class GoogleHomeTokenSensor(GoogleHomeSensorMixin, GoogleHomeTokenEntity):
    """GoogleHome Sensor class."""

    def __init__(self, coordinator, entry, device_name, local_auth_token):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

    @property
    def state(self):
        return self.get_device().local_auth_token

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeAlarmSensor(GoogleHomeSensorMixin, GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device_name, alarms):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

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

    def __init__(self, coordinator, entry, device_name, alarms):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

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

    def __init__(self, coordinator, entry, device_name, timers):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

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

    def __init__(self, coordinator, entry, device_name, alarms):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device_name

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
