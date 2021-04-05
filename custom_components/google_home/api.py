"""Sample API Client."""
from asyncio import gather
import logging
from typing import List, Optional

from aiohttp import ClientError, ClientSession
from aiohttp.client_exceptions import ClientConnectorError
from glocaltokens.client import Device, GLocalAuthenticationTokens
from glocaltokens.utils.token import is_aas_et
from zeroconf import Zeroconf

from homeassistant.const import HTTP_NOT_FOUND, HTTP_OK, HTTP_UNAUTHORIZED
from homeassistant.core import HomeAssistant

from .const import (
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DELETE,
    API_RETURNED_UNKNOWN,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
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
                    ip_address=device.ip,
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
        url = "https://{ip_address}:{port}/{endpoint}".format(
            ip_address=ip_address, port=str(port), endpoint=api_endpoint
        )
        return url

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
                            "compatable and has no alarms/timers. "
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
                        "the device is either offline or is not compatable "
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

    async def delete_timer_or_alarm(
        self, device: GoogleHomeDevice, item_to_delete: str
    ) -> None:
        """Deletes a timer or alarm.
        Can also delete multiple if a list is provided (Not implemented yet)."""

        url = self.create_url(str(device.ip_address), PORT, API_ENDPOINT_DELETE)

        # We need to remove charset=UTF-8 or else it will return a 400 BAD request.
        # I think this is because of the character "/" in the id string.
        HEADERS.update(
            {
                HEADER_CAST_LOCAL_AUTH: device.auth_token,
                HEADER_CONTENT_TYPE: "application/json",
            }
        )

        data = {"ids": [item_to_delete]}

        item_type = item_to_delete.split("/")[0]

        _LOGGER.debug(
            "Deleting %s from Google Home device %s - %s - " "Raw data: %s",
            item_type,
            device.name,
            url,
            data,
        )

        try:
            async with self._session.post(
                url, json=data, headers=HEADERS, timeout=TIMEOUT
            ) as response:
                if response.status == HTTP_OK:
                    resp = await response.json()
                    if resp:
                        if "success" in resp:
                            if resp["success"]:
                                _LOGGER.debug(
                                    "Successfully deleted %s for %s",
                                    item_type,
                                    device.name,
                                )
                            else:
                                _LOGGER.debug(
                                    "Couldn't delete %s for %s - %s",
                                    item_type,
                                    device.name,
                                    resp,
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
                                resp,
                            )
                else:
                    _LOGGER.error(
                        "Failed to delete %s for %s, API returned" " %d: %s",
                        item_type,
                        device.name,
                        response.status,
                        response,
                    )
        except ClientConnectorError:
            _LOGGER.debug(
                (
                    "Failed to connect to %s device. "
                    "The device is probably offline. Will retry later."
                ),
                device.name,
            )
        except ClientError as ex:
            # Make sure that we log the exception if one occurred.
            # The only reason we do this broad is so we easily can
            # debug the application.
            _LOGGER.error(
                "Request error: %s",
                ex,
            )
