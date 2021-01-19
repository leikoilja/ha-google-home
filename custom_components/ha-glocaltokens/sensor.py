"""Sensor platform for Google local authentication token fetching."""
from .const import DEFAULT_NAME
from .const import DOMAIN
from .const import GLOCALTOKENS_DEVICE_NAME
from .const import GLOCALTOKENS_TOKEN
from .const import ICON
from .entity import GlocaltokensEntity


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for device in coordinator.data:
        if device.get(GLOCALTOKENS_TOKEN):
            async_add_devices([GlocaltokensSensor(coordinator, entry, device)])


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
        return f"{DEFAULT_NAME} {self._name}"

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
