"""The errors of GoogleHome integration."""

from typing import Literal

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class InvalidMasterToken(Exception):
    """Error to indicate the master token is invalid.

    It's raised only while the config flow signs in, which turns it into a form error.
    """


class AlarmsAndTimersNotFetched(HomeAssistantError):
    """Error to indicate an action couldn't get a device's current alarms and timers."""

    def __init__(
        self, device_name: str, cause: DeviceRequestFailed | None = None
    ) -> None:
        """Name the device in the message, and say to refresh if the cause needs it."""
        self.refresh_needed = cause is not None and cause.refresh_needed
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=(
                "alarms_and_timers_not_fetched_token_rejected_polling_off"
                if self.refresh_needed
                else "alarms_and_timers_not_fetched"
            ),
            translation_placeholders={"device": device_name},
        )
        self.device_name = device_name


class AlarmsAndTimersNotDeleted(HomeAssistantError):
    """Error to indicate a device didn't confirm deleting alarms or timers."""

    def __init__(
        self, device_name: str, cause: DeviceRequestFailed | None = None
    ) -> None:
        """Name the device in the message, and say to refresh if the cause needs it."""
        self.refresh_needed = cause is not None and cause.refresh_needed
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=(
                "alarms_and_timers_not_deleted_token_rejected_polling_off"
                if self.refresh_needed
                else "alarms_and_timers_not_deleted"
            ),
            translation_placeholders={"device": device_name},
        )
        self.device_name = device_name


# Why a device didn't do what it was asked, or didn't confirm it
type RequestFailure = Literal[
    "offline", "no_reply", "token_rejected", "not_ready", "request_failed"
]


class DeviceRequestFailed(HomeAssistantError):
    """Error to indicate a device didn't carry out an action, or didn't confirm it."""

    def __init__(
        self, device_name: str, reason: RequestFailure, *, polling_off: bool = False
    ) -> None:
        """Name the device and the reason in the message.

        With polling_off, a rejected token's message says to refresh, as no update
        asks Google for a new token by itself.
        """
        key = f"device_{reason}"
        # The error of a delete, which wraps this one, reads it too
        self.refresh_needed = polling_off and reason == "token_rejected"
        if self.refresh_needed:
            key = "device_token_rejected_polling_off"
        super().__init__(
            translation_domain=DOMAIN,
            # device_offline, device_no_reply, device_token_rejected,
            # device_token_rejected_polling_off, device_not_ready or
            # device_request_failed
            translation_key=key,
            translation_placeholders={"device": device_name},
        )
        self.device_name = device_name
        self.reason = reason
