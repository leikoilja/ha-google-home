"""Sample API Client."""
import logging
from asyncio import gather

import aiohttp
from glocaltokens.client import GLocalAuthenticationTokens
from glocaltokens.utils.token import is_aas_et
from homeassistant.const import HTTP_NOT_FOUND
from homeassistant.const import HTTP_OK
from homeassistant.const import HTTP_UNAUTHORIZED
from zeroconf import Zeroconf

from .const import API_ENDPOINT_ALARMS
from .const import API_RETURNED_UNKNOWN
from .const import HEADER_CAST_LOCAL_AUTH
from .const import HEADERS
from .const import JSON_ALARM
from .const import JSON_TIMER
from .const import LABEL_ALARMS
from .const import LABEL_TIMERS
from .const import PORT
from .const import SUPPORTED_HARDWARE_LIST
from .const import TIMEOUT
from .exceptions import InvalidMasterToken


_LOGGER: logging.Logger = logging.getLogger(__package__)


class GlocaltokensApiClient:
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
        self._client = GLocalAuthenticationTokens(
            username=username, password=password, android_id=android_id
        )
        self.google_devices = []
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

            self.google_devices = await self.hass.async_add_executor_job(
                _get_google_devices
            )
        return self.google_devices

    async def get_android_id(self):
        """Generate random android_id"""

        def _get_android_id():
            return self._client.get_android_id()

        return await self.hass.async_add_executor_job(_get_android_id)

    @staticmethod
    def create_url(ip, port, api_endpoint):
        """Creates url to endpoint.
        Note: port argument is unused because all request must be done to 8443"""
        url = "https://{ip}:{port}/{endpoint}".format(
            ip=ip, port=str(port), endpoint=api_endpoint
        )
        return url

    async def get_alarms_and_timers(self, device):
        """Fetches timers and alarms from google device"""
        url = self.create_url(device.ip, PORT, API_ENDPOINT_ALARMS)
        _LOGGER.debug(
            "Fetching data from Google Home device {device} - {url}".format(
                device=device.device_name, url=url
            )
        )
        HEADERS[HEADER_CAST_LOCAL_AUTH] = device.local_auth_token

        resp = None
        async with self._session.get(url, headers=HEADERS, timeout=TIMEOUT) as response:
            if response.status == HTTP_OK:
                resp = await response.json()
            elif response.status == HTTP_UNAUTHORIZED:
                # If token is invalid - force reload homegraph providing new token and rerun the task
                _LOGGER.debug(
                    "Failed to fetch data from {device} due to invalid token. Will refresh the token and try again".format(
                        device=device.device_name,
                    )
                )
                self.google_devices = []
            elif response.status == HTTP_NOT_FOUND:
                _LOGGER.debug(
                    "Failed to fetch data from {device}, API returned {code}: The device(hardware='{hardware}') is not Google Home compatable and has no alarms/timers".format(
                        device=device.device_name,
                        code=response.status,
                        hardware=device.hardware,
                    )
                )
            else:
                _LOGGER.error(
                    "Failed to fetch {device} data, API returned {code}: {response}".format(
                        device=device.device_name,
                        code=response.status,
                        response=response,
                    )
                )

        if resp:
            if JSON_TIMER in resp or JSON_ALARM in resp:
                setattr(device, LABEL_TIMERS, resp.get(JSON_TIMER, []))
                setattr(device, LABEL_ALARMS, resp.get(JSON_ALARM, []))
            else:
                _LOGGER.error(
                    "For device {device} - {error}".format(
                        device=device.device_name,
                        error=API_RETURNED_UNKNOWN,
                    )
                )
        return device

    async def update_google_devices_information(self):
        """Retrieves devices from glocaltokens and fetches alarm/timer data from each of the device"""

        devices = await self.get_google_devices()

        # Gives the user a warning if the device is offline
        for device in devices:
            if not device.ip:
                _LOGGER.debug(
                    "Failed to fetch timers/alarms information from device {device}. We could not determine it's IP address, the device is either offline or is not compatable Google Home device. Will try again later.".format(
                        device=device.device_name
                    )
                )

        coordinator_data = await gather(
            *[
                self.get_alarms_and_timers(device)
                for device in devices
                if device.ip and device.hardware in SUPPORTED_HARDWARE_LIST
            ]
        )

        return coordinator_data
