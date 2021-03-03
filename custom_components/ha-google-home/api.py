"""Sample API Client."""
import logging
import ssl

import aiohttp
from glocaltokens.client import GLocalAuthenticationTokens
from glocaltokens.utils.token import is_aas_et
from homeassistant.const import HTTP_OK, HTTP_NOT_FOUND

from .const import API_ENDPOINT_ALARMS
from .const import API_RETURNED_UNKNOWN
from .const import HEADER_CAST_LOCAL_AUTH
from .const import HEADERS
from .const import PORT
from .const import TIMEOUT
from .const import LABEL_ALARMS
from .const import LABEL_TIMERS
from .const import LABEL_TOKEN
from .const import JSON_ALARM
from .const import JSON_TIMER
from .exceptions import InvalidMasterToken


_LOGGER: logging.Logger = logging.getLogger(__package__)


class GlocaltokensApiClient:
    def __init__(
        self,
        hass,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        android_id: str,
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

    async def async_get_master_token(self):
        """Get master API token"""

        def _get_master_token():
            return self._client.get_master_token()

        master_token = await self.hass.async_add_executor_job(_get_master_token)
        if is_aas_et(master_token) is False:
            raise InvalidMasterToken
        return master_token

    async def get_google_devices(self, zeroconf_instance):
        """Get google device authentication tokens.
        Note this method will fetch necessary access tokens if missing"""

        def _get_google_devices():
            return self._client.get_google_devices(zeroconf_instance=zeroconf_instance)

        return await self.hass.async_add_executor_job(_get_google_devices)

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

    async def get_alarms_and_timers(self, url, device):
        """Fetches timers and alarms from google device"""
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
            elif response.status == HTTP_NOT_FOUND:
                _LOGGER.debug(
                    "Failed to fetch data from {device}, API returned {code}: The devics is not Google Home compatable and has to alarms/timers".format(
                        device=device.device_name,
                        code=response.status,
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
        return resp

    async def get_google_devices_information(self, zeroconf_instance):
        """Retrieves devices from glocaltokens and fetches alarm/timer data from each of the device"""

        _LOGGER.debug("Fetching sensor data...")

        offline_devices = []
        devices = await self.get_google_devices(zeroconf_instance)
        coordinator_data = {}

        for device in devices:
            timers = []
            alarms = []

            if device.ip:
                url = self.create_url(device.ip, PORT, API_ENDPOINT_ALARMS)

                device_data_json = await self.get_alarms_and_timers(
                    url,
                    device,
                )

                if device_data_json:
                    if (
                        JSON_TIMER in device_data_json or
                        JSON_ALARM in device_data_json
                    ):
                        timers = device_data_json.get(JSON_TIMER)
                        alarms = device_data_json.get(JSON_ALARM)
                    else:
                        _LOGGER.error(
                            "For device {device} - {error}".format(
                                device=device.device_name,
                                error=API_RETURNED_UNKNOWN,
                            )
                        )
            else:
                offline_devices.append(device)

            coordinator_data[device.device_name] = {
                LABEL_TOKEN: device.local_auth_token,
                LABEL_ALARMS: alarms,
                LABEL_TIMERS: timers,
            }

        # Gives the user a warning if the device is offline,
        # but will not remove entities or device from HA device registry
        if offline_devices:
            for device in offline_devices:
                _LOGGER.debug(
                    "Failed to fetch timers/alarms information from device {device}. We could not determine it's IP address, the device is either offline or is not compatable Google Home device. Will try again later.".format(
                        device=device.device_name
                    )
                )
        return coordinator_data
