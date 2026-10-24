"""The errors of GoogleHome integration."""

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class InvalidMasterToken(HomeAssistantError):
    """Error to indicate the master token is invalid."""


class AlarmsAndTimersNotFetched(HomeAssistantError):
    """Error to indicate an action couldn't get a device's current alarms and timers."""

    def __init__(self, device_name: str) -> None:
        """Name the device in the message."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key="alarms_and_timers_not_fetched",
            translation_placeholders={"device": device_name},
        )
        self.device_name = device_name
