"""The errors of GoogleHome integration."""

from typing import Literal

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


class AlarmsAndTimersNotDeleted(HomeAssistantError):
    """Error to indicate a device didn't confirm deleting alarms or timers."""

    def __init__(self, device_name: str) -> None:
        """Name the device in the message."""
        super().__init__(
            translation_domain=DOMAIN,
            translation_key="alarms_and_timers_not_deleted",
            translation_placeholders={"device": device_name},
        )
        self.device_name = device_name


# Why a device didn't do what it was asked, or didn't confirm it
type RequestFailure = Literal[
    "offline", "no_reply", "token_rejected", "not_ready", "request_failed"
]


class DeviceRequestFailed(HomeAssistantError):
    """Error to indicate a device didn't carry out an action, or didn't confirm it."""

    def __init__(self, device_name: str, reason: RequestFailure) -> None:
        """Name the device and the reason in the message."""
        super().__init__(
            translation_domain=DOMAIN,
            # device_offline, device_no_reply, device_token_rejected,
            # device_not_ready or device_request_failed
            translation_key=f"device_{reason}",
            translation_placeholders={"device": device_name},
        )
        self.device_name = device_name
        self.reason = reason
