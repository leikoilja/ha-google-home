"""Sample API Client."""
from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from typing import List, Literal, cast

from aiohttp import ClientError, ClientSession
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError
from glocaltokens.client import Device, GLocalAuthenticationTokens
from glocaltokens.utils.token import is_aas_et
from zeroconf import Zeroconf

from homeassistant.core import HomeAssistant

from .const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARM_VOLUME,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DO_NOT_DISTURB,
    API_ENDPOINT_REBOOT,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    JSON_ALARM,
    JSON_ALARM_VOLUME,
    JSON_NOTIFICATIONS_ENABLED,
    JSON_TIMER,
    PORT,
    TIMEOUT,
)
from .exceptions import InvalidMasterToken
from .models import GoogleHomeDevice
from .types import AlarmJsonDict, JsonDict, TimerJsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GlocaltokensApiClient:
    """API client"""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        username: str | None = None,
        password: str | None = None,
        master_token: str | None = None,
        android_id: str | None = None,
        zeroconf_instance: Zeroconf | None = None,
    ):
        """Sample API Client."""
        self.hass = hass
        self._username = username
        self._password = password
        self._session = session
        self._android_id = android_id
        verbose = _LOGGER.level == logging.DEBUG
        self._client = GLocalAuthenticationTokens(
            username=username,
            password=password,
            master_token=master_token,
            android_id=android_id,
            verbose=verbose,
        )
        self.google_devices: list[GoogleHomeDevice] = []
        self.zeroconf_instance = zeroconf_instance

    async def async_get_master_token(self) -> str:
        """Get master API token"""

        def _get_master_token() -> str | None:
            return self._client.get_master_token()

        master_token = await self.hass.async_add_executor_job(_get_master_token)
        if master_token is None or is_aas_et(master_token) is False:
            raise InvalidMasterToken
        return master_token

    async def get_google_devices(self) -> list[GoogleHomeDevice]:
        """Get google device authentication tokens.
        Note this method will fetch necessary access tokens if missing"""

        if not self.google_devices:

            def _get_google_devices() -> list[Device]:
                return self._client.get_google_devices(
                    zeroconf_instance=self.zeroconf_instance,
                    force_homegraph_reload=True,
                )

            google_devices = await self.hass.async_add_executor_job(_get_google_devices)
            self.google_devices = [
                GoogleHomeDevice(
                    device_id=device.device_id,
                    name=device.device_name,
                    auth_token=device.local_auth_token,
                    ip_address=device.ip_address,
                    hardware=device.hardware,
                )
                for device in google_devices
            ]
        return self.google_devices

    async def get_android_id(self) -> str:
        """Generate random android_id"""

        def _get_android_id() -> str:
            return self._client.get_android_id()

        return await self.hass.async_add_executor_job(_get_android_id)

    @staticmethod
    def create_url(ip_address: str, port: int, api_endpoint: str) -> str:
        """Creates url to endpoint.
        Note: port argument is unused because all request must be done to 8443"""
        return f"https://{ip_address}:{port}/{api_endpoint}"

    async def update_google_devices_information(self) -> list[GoogleHomeDevice]:
        """Retrieves devices from glocaltokens and
        fetches alarm/timer data from each of the device"""

        devices = await self.get_google_devices()

        # Gives the user a warning if the device is offline
        for device in devices:
            if not device.ip_address and device.available:
                device.available = False
                _LOGGER.debug(
                    (
                        "Failed to fetch timers/alarms information "
                        "from device %s. We could not determine its IP address, "
                        "the device is either offline or is not compatible "
                        "Google Home device. Will try again later."
                    ),
                    device.name,
                )

        coordinator_data = await asyncio.gather(
            *[
                self.collect_data_from_endpoints(device)
                for device in devices
                if device.ip_address and device.auth_token
            ]
        )
        return coordinator_data

    async def collect_data_from_endpoints(
        self, device: GoogleHomeDevice
    ) -> GoogleHomeDevice:
        """Collect data from different endpoints."""
        device = await self.update_alarms_and_timers(device)
        device = await self.update_alarm_volume(device)
        device = await self.update_do_not_disturb(device)
        return device

    async def update_alarms_and_timers(
        self, device: GoogleHomeDevice
    ) -> GoogleHomeDevice:
        """Fetches timers and alarms from google device"""
        response = await self.request(
            method="GET", endpoint=API_ENDPOINT_ALARMS, device=device, polling=True
        )

        if response is not None:
            if JSON_TIMER in response and JSON_ALARM in response:
                device.set_timers(cast(List[TimerJsonDict], response[JSON_TIMER]))
                device.set_alarms(cast(List[AlarmJsonDict], response[JSON_ALARM]))
                _LOGGER.debug(
                    "Successfully retrieved alarms and timers from %s. Response: %s",
                    device.name,
                    response,
                )
            else:
                _LOGGER.error(
                    (
                        "Failed to parse fetched alarms and timers for device %s - "
                        "API returned unknown json structure. "
                        "Received = %s"
                    ),
                    device.name,
                    response,
                )
        return device

    async def delete_alarm_or_timer(
        self, device: GoogleHomeDevice, item_to_delete: str
    ) -> None:
        """Deletes a timer or alarm.
        Can also delete multiple if a list is provided (Not implemented yet)."""

        data = {"ids": [item_to_delete]}

        item_type = item_to_delete.split("/")[0]

        _LOGGER.debug(
            "Deleting %s from Google Home device %s - Raw data: %s",
            item_type,
            device.name,
            data,
        )

        response = await self.request(
            method="POST", endpoint=API_ENDPOINT_ALARM_DELETE, device=device, data=data
        )

        if response is not None:
            if "success" in response:
                if response["success"]:
                    _LOGGER.debug(
                        "Successfully deleted %s for %s",
                        item_type,
                        device.name,
                    )
                else:
                    _LOGGER.error(
                        "Couldn't delete %s for %s - %s",
                        item_type,
                        device.name,
                        response,
                    )
            else:
                _LOGGER.error(
                    (
                        "Failed to get a confirmation that the %s"
                        "was deleted for device %s. "
                        "Received = %s"
                    ),
                    item_type,
                    device.name,
                    response,
                )

    async def reboot_google_device(self, device: GoogleHomeDevice) -> None:
        """Reboots a Google Home device if it supports this."""

        # "now" means reboot and "fdr" means factory reset (Not implemented).
        data = {"params": "now"}

        _LOGGER.debug(
            "Trying to reboot Google Home device %s",
            device.name,
        )

        response = await self.request(
            method="POST", endpoint=API_ENDPOINT_REBOOT, device=device, data=data
        )

        if response is not None:
            # It will return true even if the device does not support rebooting.
            _LOGGER.info(
                "Successfully asked %s to reboot.",
                device.name,
            )

    async def update_do_not_disturb(
        self, device: GoogleHomeDevice, enable: bool | None = None
    ) -> GoogleHomeDevice:
        """Gets or sets the do not disturb setting on a Google Home device."""

        data = None
        polling = False

        if enable is not None:
            # Setting is inverted on device
            data = {JSON_NOTIFICATIONS_ENABLED: not enable}
            _LOGGER.debug(
                "Setting Do Not Disturb setting to %s on Google Home device %s",
                enable,
                device.name,
            )
        else:
            polling = True
            _LOGGER.debug(
                "Getting Do Not Disturb setting from Google Home device %s",
                device.name,
            )

        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_DO_NOT_DISTURB,
            device=device,
            data=data,
            polling=polling,
        )
        if response is not None:
            if JSON_NOTIFICATIONS_ENABLED in response:
                enabled = not bool(response[JSON_NOTIFICATIONS_ENABLED])
                _LOGGER.debug(
                    "Received Do Not Disturb setting from Google Home device %s"
                    " - Enabled: %s",
                    device.name,
                    enabled,
                )

                device.set_do_not_disturb(enabled)
            else:
                _LOGGER.debug(
                    (
                        "Unexpected response from Google Home device '%s' "
                        "when fetching DND status - %s"
                    ),
                    device.name,
                    response,
                )

        return device

    async def update_alarm_volume(
        self, device: GoogleHomeDevice, volume: int | None = None
    ) -> GoogleHomeDevice:
        """Gets or sets the alarm volume setting on a Google Home device."""

        data: JsonDict | None = None
        polling = False

        if volume is not None:
            # Setting is inverted on device
            volume_float = float(volume / 100)
            data = {JSON_ALARM_VOLUME: volume_float}
            _LOGGER.debug(
                "Setting alarm volume to %d(float=%f) on Google Home device %s",
                volume,
                volume_float,
                device.name,
            )
        else:
            polling = True
            _LOGGER.debug(
                "Getting alarm volume from Google Home device %s",
                device.name,
            )

        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_ALARM_VOLUME,
            device=device,
            data=data,
            polling=polling,
        )
        if response:
            if JSON_ALARM_VOLUME in response:
                if polling:
                    volume_raw = str(response[JSON_ALARM_VOLUME])
                    volume_int = round(float(volume_raw) * 100)
                    _LOGGER.debug(
                        "Received alarm volume from Google Home device %s"
                        " - Volume: %d(raw=%s)",
                        device.name,
                        volume_int,
                        volume_raw,
                    )
                else:
                    volume_int = volume  # type: ignore
                    _LOGGER.debug(
                        "Successfully set alarm volume to %d "
                        "on Google Home device %s",
                        volume,
                        device.name,
                    )
                device.set_alarm_volume(volume_int)
            else:
                _LOGGER.debug(
                    (
                        "Unexpected response from Google Home device '%s' "
                        "when fetching alarm volume setting - %s"
                    ),
                    device.name,
                    response,
                )

        return device

    async def request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        device: GoogleHomeDevice,
        data: JsonDict | None = None,
        polling: bool = False,
    ) -> JsonDict | None:
        """Shared request method"""

        if device.ip_address is None:
            _LOGGER.warning("Device %s doesn't have an IP address!", device.name)
            return None

        if device.auth_token is None:
            _LOGGER.warning("Device %s doesn't have an auth token!", device.name)
            return None

        url = self.create_url(device.ip_address, PORT, endpoint)

        headers: dict[str, str] = {
            HEADER_CAST_LOCAL_AUTH: device.auth_token,
            HEADER_CONTENT_TYPE: "application/json",
        }

        _LOGGER.debug(
            "Requesting endpoint %s for Google Home device %s - %s",
            endpoint,
            device.name,
            url,
        )

        resp = None

        try:
            async with self._session.request(
                method, url, json=data, headers=headers, timeout=TIMEOUT
            ) as response:
                if response.status == HTTPStatus.OK:
                    try:
                        resp = await response.json()
                    except ContentTypeError:
                        resp = {}
                    device.available = True
                elif response.status == HTTPStatus.UNAUTHORIZED:
                    # If token is invalid - force reload homegraph providing new token
                    # and rerun the task.
                    if polling:
                        _LOGGER.debug(
                            (
                                "Failed to fetch data from %s due to invalid token. "
                                "Will refresh the token and try again."
                            ),
                            device.name,
                        )
                    else:
                        _LOGGER.warning(
                            "Failed to send the request to %s due to invalid token. "
                            "Token will be refreshed, please try again later.",
                            device.name,
                        )
                    # We need to retry the update task instead of just cleaning the list
                    self.google_devices = []
                    device.available = False
                elif response.status == HTTPStatus.NOT_FOUND:
                    _LOGGER.debug(
                        (
                            "Failed to perform request to %s, API returned %d. "
                            "The device(hardware='%s') is possibly not Google Home "
                            "compatible and has no alarms/timers. "
                            "Will retry later."
                        ),
                        device.name,
                        response.status,
                        device.hardware,
                    )
                    device.available = False
                else:
                    _LOGGER.error(
                        "Failed to access %s, API returned %d: %s",
                        device.name,
                        response.status,
                        response,
                    )
                    device.available = False
        except ClientConnectorError:
            logger_func = _LOGGER.debug if polling else _LOGGER.warning
            logger_func(
                "Failed to connect to %s device. The device is probably offline.",
                device.name,
            )
            device.available = False
        except ClientError as ex:
            # Make sure that we log the exception from the client if one occurred.
            _LOGGER.error(
                "Request from %s device error: %s",
                device.name,
                ex,
            )
            device.available = False
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "%s device timed out while performing a request to it - Raw data: %s",
                device.name,
                data,
            )
            device.available = False

        return resp
