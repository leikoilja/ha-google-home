"""GlocaltokensEntity class"""
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .const import MANUFACTURER
from .const import NAME
from .const import DEFAULT_NAME
from .const import VERSION


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
