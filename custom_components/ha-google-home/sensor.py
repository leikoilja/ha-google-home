"""Sensor platform for Google local authentication token fetching."""
from homeassistant.const import STATE_OFF
from homeassistant.const import STATE_ON

from .const import DOMAIN
from .const import FIRE_TIME_IN_S
from .entity import GoogleHomeAlarmEntity
from .entity import GoogleHomeEntity
from .entity import GoogleHomeTimersEntity
from .utils import format_alarm_information
from .utils import format_timer_information


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for device in coordinator.data:
        if device.local_auth_token:
            async_add_devices(
                [
                    GoogleHomeAlarmSensor(coordinator, entry, device),
                    GoogleHomeTimerSensor(coordinator, entry, device),
                    GoogleHomeSensor(coordinator, entry, device),
                ]
            )


class GoogleHomeSensor(GoogleHomeEntity):
    """GoogleHome Sensor class."""

    def __init__(self, coordinator, entry, device):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device.device_name
        self._state = device.local_auth_token

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeAlarmSensor(GoogleHomeAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device.device_name
        self._alarms = [format_alarm_information(alarm) for alarm in device.alarms]

        if len(self._alarms) > 0:
            self._state = self._alarms[0][FIRE_TIME_IN_S]
        else:
            self._state = STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "alarms": self._alarms,
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GoogleHomeTimerSensor(GoogleHomeTimersEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device.device_name
        self._timers = [format_timer_information(timer) for timer in device.timers]

        if len(self._timers) > 0:
            self._state = STATE_ON
        else:
            self._state = STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "timers": self._timers,
            "device": str(self.name),
            "integration": DOMAIN,
        }
