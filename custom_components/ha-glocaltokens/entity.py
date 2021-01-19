"""GlocaltokensEntity class"""
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .const import MANUFACTURER
from .const import NAME
from .const import VERSION


class GlocaltokensEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self._name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": NAME,
            "model": VERSION,
            "manufacturer": MANUFACTURER,
        }

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "id": str(self.unique_id),
            "integration": DOMAIN,
        }
