"""The errors of GoogleHome integration."""
from homeassistant.exceptions import HomeAssistantError


class InvalidMasterToken(HomeAssistantError):
    """Error to indicate the master token is invalid."""
