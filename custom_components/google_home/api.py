"""Sample API Client."""
from asyncio import gather
import logging
from typing import List

import aiohttp
from glocaltokens.client import GLocalAuthenticationTokens
from glocaltokens.utils.token import is_aas_et
from zeroconf import Zeroconf

from homeassistant.const import HTTP_NOT_FOUND, HTTP_OK, HTTP_UNAUTHORIZED

from .const import (
    API_ENDPOINT_ALARMS,
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
        hass,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        android_id: str = None,
        zeroconf_instance: Zeroconf = None,
    ) -> None:
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
            android_id=android_id,
            verbose=verbose,
        )
        self.google_devices: List[GoogleHomeDevice] = []
        self.zeroconf_instance = zeroconf_instance

    async def async_get_master_token(self):
        """Get master API token"""

        def _get_master_token():
            return self._client.get_master_token()

        master_token = await self.hass.async_add_executor_job(_get_master_token)
        if is_aas_et(master_token) is False:
            raise InvalidMasterToken
        return master_token

    async def get_google_devices(self):
        """Get google device authentication tokens.
        Note this method will fetch necessary access tokens if missing"""

        if not self.google_devices:

            def _get_google_devices():
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

    async def get_android_id(self):
        """Generate random android_id"""

        def _get_android_id():
            return self._client.get_android_id()

        return await self.hass.async_add_executor_job(_get_android_id)

    @staticmethod
    def create_url(ip_address, port, api_endpoint):
        """Creates url to endpoint.
        Note: port argument is unused because all request must be done to 8443"""
        url = "https://{ip_address}:{port}/{endpoint}".format(
            ip_address=ip_address, port=str(port), endpoint=api_endpoint
        )
        return url

    async def get_alarms_and_timers(self, device):
        """Fetches timers and alarms from google device"""
        url = self.create_url(device.ip_address, PORT, API_ENDPOINT_ALARMS)
        _LOGGER.debug(
            "Fetching data from Google Home device %s - %s",
            device.name,
            url,
        )
        HEADERS[HEADER_CAST_LOCAL_AUTH] = device.auth_token

        resp = None

        try:
            async with self._session.get(
                url, headers=HEADERS, timeout=TIMEOUT
            ) as response:
                if response.status == HTTP_OK:
                    resp = await response.json()
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
                elif response.status == HTTP_NOT_FOUND:
                    device.available = False
                    _LOGGER.debug(
                        (
                            "Failed to fetch data from %s, API returned %d. "
                            "The device(hardware='%s') is not Google Home "
                            "compatable and has no alarms/timers."
                        ),
                        device.name,
                        response.status,
                        device.hardware,
                    )
                else:
                    _LOGGER.error(
                        "Failed to fetch %s data, API returned %d: %s",
                        device.name,
                        response.status,
                        response,
                    )
        except aiohttp.ClientError as ex:
            # Make sure that we log the exception if one occurred.
            # The only reason we do this broad is so we easily can
            # debug the application.
            _LOGGER.error(
                "Request error: %s",
                ex,
            )
        finally:
            if resp:
                if JSON_TIMER in resp or JSON_ALARM in resp:
                    device.set_timers(resp.get(JSON_TIMER))
                    device.set_alarms(resp.get(JSON_ALARM))
                else:
                    _LOGGER.error(
                        "For device %s - %s",
                        device.name,
                        API_RETURNED_UNKNOWN,
                    )
        return device

    async def update_google_devices_information(self):
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
                self.get_alarms_and_timers(device)
                for device in devices
                if device.ip_address and device.available
            ]
        )

        return coordinator_data
