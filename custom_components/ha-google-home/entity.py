from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME
from .const import DOMAIN
from .const import ICON_ALARMS
from .const import ICON_TIMERS
from .const import ICON_TOKEN
from .const import LABEL_ALARMS
from .const import LABEL_NEXT_ALARM
from .const import LABEL_TIMERS
from .const import LABEL_TOKEN
from .const import MANUFACTURER
from .const import VERSION


class GoogleHomeTokenEntity(CoordinatorEntity):
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
        return f"{self._name} {LABEL_TOKEN}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/{LABEL_TOKEN}"

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
        return "google_home__custom_device_class"


class GoogleHomeAlarmEntity(CoordinatorEntity):
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
        return f"{self._name} {LABEL_ALARMS}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/{LABEL_ALARMS}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state


class GoogleHomeNextAlarmEntity(CoordinatorEntity):
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
        return f"{self._name} {LABEL_NEXT_ALARM}"

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}/{LABEL_NEXT_ALARM}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_ALARMS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state


class GoogleHomeTimersEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._name} {LABEL_TIMERS}"

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
        return f"{self._name}/{LABEL_TIMERS}"

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return ICON_TIMERS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
