"""Sample API Client."""
from asyncio import gather
import json
import logging
from typing import Dict, List, Optional

from aiohttp import ClientError, ClientSession
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError
from glocaltokens.client import Device, GLocalAuthenticationTokens
from glocaltokens.utils.token import is_aas_et
from zeroconf import Zeroconf

from homeassistant.const import HTTP_NOT_FOUND, HTTP_OK, HTTP_UNAUTHORIZED
from homeassistant.core import HomeAssistant

from .const import (
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DELETE,
    API_ENDPOINT_REBOOT,
    API_RETURNED_UNKNOWN,
    HEADER_CAST_LOCAL_AUTH,
    HEADERS,
    JSON_ALARM,
    JSON_TIMER,
    PORT,
    TIMEOUT,
)
from .exceptions import InvalidMasterToken
from .models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GlocaltokensApiClient:
    """API client"""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        username: Optional[str] = None,
        password: Optional[str] = None,
        master_token: Optional[str] = None,
        android_id: Optional[str] = None,
        zeroconf_instance: Optional[Zeroconf] = None,
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
        self.google_devices: List[GoogleHomeDevice] = []
        self.zeroconf_instance = zeroconf_instance

    async def async_get_master_token(self) -> str:
        """Get master API token"""

        def _get_master_token() -> Optional[str]:
            return self._client.get_master_token()

        master_token = await self.hass.async_add_executor_job(_get_master_token)
        if master_token is None or is_aas_et(master_token) is False:
            raise InvalidMasterToken
        return master_token

    async def get_google_devices(self) -> List[GoogleHomeDevice]:
        """Get google device authentication tokens.
        Note this method will fetch necessary access tokens if missing"""

        if not self.google_devices:

            def _get_google_devices() -> List[Device]:
                return self._client.get_google_devices(
                    zeroconf_instance=self.zeroconf_instance,
                    force_homegraph_reload=True,
                )

            google_devices = await self.hass.async_add_executor_job(_get_google_devices)
            self.google_devices = [
                GoogleHomeDevice(
                    name=device.device_name,
                    auth_token=device.local_auth_token,
                    ip_address=device.ip_address,
                    hardware=device.hardware,
                )
                for device in google_devices
            ]
        return self.google_devices

    async def get_android_id(self) -> Optional[str]:
        """Generate random android_id"""

        def _get_android_id() -> Optional[str]:
            return self._client.get_android_id()

        return await self.hass.async_add_executor_job(_get_android_id)

    @staticmethod
    def create_url(ip_address: str, port: int, api_endpoint: str) -> str:
        """Creates url to endpoint.
        Note: port argument is unused because all request must be done to 8443"""
        return f"https://{ip_address}:{port}/{api_endpoint}"

    async def get_alarms_and_timers(
        self, device: GoogleHomeDevice, ip_address: str, auth_token: str
    ) -> GoogleHomeDevice:
        """Fetches timers and alarms from google device"""
        url = self.create_url(ip_address, PORT, API_ENDPOINT_ALARMS)
        _LOGGER.debug(
            "Fetching data from Google Home device %s - %s",
            device.name,
            url,
        )
        HEADERS[HEADER_CAST_LOCAL_AUTH] = auth_token

        resp = None

        try:
            async with self._session.get(
                url, headers=HEADERS, timeout=TIMEOUT
            ) as response:
                if response.status == HTTP_OK:
                    resp = await response.json()
                    device.available = True
                    if resp:
                        if JSON_TIMER in resp or JSON_ALARM in resp:
                            device.set_timers(resp.get(JSON_TIMER))
                            device.set_alarms(resp.get(JSON_ALARM))
                        else:
                            _LOGGER.error(
                                (
                                    "Failed to parse fetched data for device %s - %s. "
                                    "Received = %s"
                                ),
                                device.name,
                                API_RETURNED_UNKNOWN,
                                resp,
                            )
                elif response.status == HTTP_UNAUTHORIZED:
                    # If token is invalid - force reload homegraph providing new token
                    # and rerun the task.
                    _LOGGER.debug(
                        (
                            "Failed to fetch data from %s due to invalid token. "
                            "Will refresh the token and try again."
                        ),
                        device.name,
                    )
                    # We need to retry the update task instead of just cleaning the list
                    self.google_devices = []
                    device.available = False
                elif response.status == HTTP_NOT_FOUND:
                    _LOGGER.debug(
                        (
                            "Failed to fetch data from %s, API returned %d. "
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
                        "Failed to fetch %s data, API returned %d: %s",
                        device.name,
                        response.status,
                        response,
                    )
                    device.available = False
        except ClientConnectorError:
            _LOGGER.debug(
                (
                    "Failed to connect to %s device. "
                    "The device is probably offline. Will retry later."
                ),
                device.name,
            )
            device.available = False
        except ClientError as ex:
            # Make sure that we log the exception if one occurred.
            # The only reason we do this broad is so we easily can
            # debug the application.
            _LOGGER.error(
                "Request error: %s",
                ex,
            )
            device.available = False
        return device

    async def update_google_devices_information(self) -> List[GoogleHomeDevice]:
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
                        "from device %s. We could not determine it's IP address, "
                        "the device is either offline or is not compatible "
                        "Google Home device. Will try again later."
                    ),
                    device.name,
                )

        coordinator_data = await gather(
            *[
                self.get_alarms_and_timers(device, device.ip_address, device.auth_token)
                for device in devices
                if device.ip_address and device.auth_token
            ]
        )
        return coordinator_data

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

        response = await self.post(
            endpoint=API_ENDPOINT_DELETE, data=json.dumps(data), device=device
        )

        if response:
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

        response = await self.post(
            endpoint=API_ENDPOINT_REBOOT, data=json.dumps(data), device=device
        )

        if response:
            # It will return true even if the device does not support rebooting.
            _LOGGER.info(
                "Successfully asked %s to reboot.",
                device.name,
            )

    async def post(
        self, endpoint: str, data: str, device: GoogleHomeDevice
    ) -> Optional[Dict[str, str]]:
        """Shared post request"""

        if device.ip_address is None:
            _LOGGER.warning("Device %s doesn't have an IP address!", device.name)
            return None

        if device.auth_token is None:
            _LOGGER.warning("Device %s doesn't have an auth token!", device.name)
            return None

        url = self.create_url(device.ip_address, PORT, endpoint)

        HEADERS[HEADER_CAST_LOCAL_AUTH] = device.auth_token

        _LOGGER.debug(
            "Requesting endpoint %s for Google Home device %s - %s",
            endpoint,
            device.name,
            url,
        )

        resp = None

        try:
            async with self._session.post(
                url, data=data, headers=HEADERS, timeout=TIMEOUT
            ) as response:
                if response.status == HTTP_OK:
                    try:
                        resp = await response.json()
                    except ContentTypeError:
                        resp = True
                else:
                    _LOGGER.error(
                        "Failed to access %s, API returned" " %d: %s",
                        device.name,
                        response.status,
                        response,
                    )
        except ClientConnectorError:
            _LOGGER.warning(
                "Failed to connect to %s device. The device is probably offline.",
                device.name,
            )
        except ClientError as ex:
            # Make sure that we log the exception from the client if one occurred.
            _LOGGER.error(
                "Request error: %s",
                ex,
            )

        return resp
