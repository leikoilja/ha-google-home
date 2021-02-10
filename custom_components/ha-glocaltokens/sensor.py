"""Sensor platform for Google local authentication token fetching."""
from homeassistant.const import STATE_OFF, STATE_ON

from .const import DEFAULT_NAME
from .const import DOMAIN
from .const import GLOCALTOKENS_DEVICE_NAME
from .const import GLOCALTOKENS_TOKEN
from .const import GLOCALTOKENS_ALARMS
from .const import GLOCALTOKENS_TIMERS
from .const import ICON
from .entity import GlocaltokensEntity


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
        self._token = device[GLOCALTOKENS_TOKEN]

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME} {self._name} token"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/token"

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "device": str(self.name),
            "integration": DOMAIN,
        }

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._token

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON

    @property
    def device_class(self):
        """Return de device class of the sensor."""
        return "glocaltokens__custom_device_class"

class GlocaltokensAlarmSensor(GlocaltokensEntity):
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
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME} {self._name} next alarm"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/next_alarm"

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            'alarms': self._alarms,
            "device": str(self.name),
            "integration": DOMAIN,
        }

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return "mdi:alarm-multiple"


class GlocaltokensTimerSensor(GlocaltokensEntity):
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
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME} {self._name} timers"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/timers"

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            'timers': self._timers,
            "device": str(self.name),
            "integration": DOMAIN,
        }

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return "mdi:timer-sand"
