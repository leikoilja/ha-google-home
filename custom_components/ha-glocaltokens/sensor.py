"""Sensor platform for Google local authentication token fetching."""
from homeassistant.const import STATE_OFF, STATE_ON

from .const import DEFAULT_NAME
from .const import DOMAIN
from .const import GLOCALTOKENS_DEVICE_NAME
from .const import GLOCALTOKENS_TOKEN
from .const import GLOCALTOKENS_ALARMS
from .const import GLOCALTOKENS_TIMERS
from .entity import GlocaltokensEntity, GlocalTimersEntity, GlocalAlarmEntity


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for device in coordinator.data:
        if device.get(GLOCALTOKENS_TOKEN):
            async_add_devices([GlocaltokensAlarmSensor(coordinator, entry, device),
                               GlocaltokensTimerSensor(coordinator, entry, device),
                               GlocaltokensSensor(coordinator, entry, device)])


class GlocaltokensSensor(GlocaltokensEntity):
    """glocaltokens Sensor class."""

    def __init__(self, coordinator, entry, device):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device[GLOCALTOKENS_DEVICE_NAME]
        self._state = device[GLOCALTOKENS_TOKEN]

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }

class GlocaltokensAlarmSensor(GlocalAlarmEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device[GLOCALTOKENS_DEVICE_NAME]
        self._alarms = device[GLOCALTOKENS_ALARMS]

        if len(self._alarms) > 0:
            self._state = self._alarms[0]['fire_time'] / 1000
        else:
            self._state = STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            'alarms': self._alarms,
            "device": str(self.name),
            "integration": DOMAIN,
        }


class GlocaltokensTimerSensor(GlocalTimersEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, entry, device):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._name = device[GLOCALTOKENS_DEVICE_NAME]
        self._timers = device[GLOCALTOKENS_TIMERS]

        if len(self._timers) > 0:
            self._state = STATE_ON
        else:
            self._state = STATE_OFF

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            'timers': self._timers,
            "device": str(self.name),
            "integration": DOMAIN,
        }
