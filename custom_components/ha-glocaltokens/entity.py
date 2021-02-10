"""GlocaltokensEntity class"""
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .const import MANUFACTURER
from .const import NAME
from .const import DEFAULT_NAME
from .const import VERSION
from .const import ICON_TOKEN, ICON_ALARMS, ICON_TIMERS


class GlocaltokensEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._name)},
            "name": f"{DEFAULT_NAME} {self._name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME} {self._name} token"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/token"

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON_TOKEN

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def device_class(self):
        """Return de device class of the sensor."""
        return "glocaltokens__custom_device_class"

class GlocalAlarmEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._name)},
            "name": f"{DEFAULT_NAME} {self._name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME} {self._name} next alarm"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/next_alarm"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

class GlocalTimersEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME} {self._name} timers"


    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._name)},
            "name": f"{DEFAULT_NAME} {self._name}",
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/timers"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_TIMERS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
