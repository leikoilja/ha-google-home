"""The errors of GoogleHome integration."""
from homeassistant import exceptions


class InvalidMasterToken(exceptions.HomeAssistantError):
    """Error to indicate the master token is invalid."""
