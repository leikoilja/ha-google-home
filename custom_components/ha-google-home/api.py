"""Sample API Client."""
import logging
import ssl

import aiohttp
from glocaltokens.client import GLocalAuthenticationTokens
from homeassistant.const import HTTP_OK

from .const import ALARMS
from .const import API_ENDPOINT_ALARMS
from .const import API_RETURNED_UNKNOWN
from .const import HEADER_CAST_LOCAL_AUTH
from .const import HEADERS
from .const import PORT
from .const import TIMEOUT
from .const import TIMERS
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
        if master_token.startswith("aas_et/") is False:
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

        async with self._session.get(url, headers=HEADERS, timeout=TIMEOUT) as response:
            if response.status != HTTP_OK:
                _LOGGER.error(
                    "Failed to fetch {device} data, API returned {error}: {reason}".format(
                        device=device.device_name,
                        error=response.status_code,
                        reason=response.text,
                    )
                )
                return
            return await response.json()

    async def get_google_devices_information(self, zeroconf_instance):
        """Retrieves devices from glocaltokens and fetches alarm/timer data from each of the device"""

        _LOGGER.debug("Fetching sensor data...")

        offline_devices = []
        devices = await self.get_google_devices(zeroconf_instance)

        for device in devices:
            timers = []
            alarms = []

            if device.ip:
                url = self.create_url(device.ip, PORT, API_ENDPOINT_ALARMS)

                try:
                    device_data_json = await self.get_alarms_and_timers(
                        url,
                        device,
                    )

                    if (
                        TIMERS not in device_data_json or
                        ALARMS not in device_data_json
                    ):
                        _LOGGER.error(
                            "For device {device} - {error}".format(
                                device=device.device_name,
                                error=API_RETURNED_UNKNOWN,
                            )
                        )

                    timers = device_data_json.get(TIMERS)
                    alarms = device_data_json.get(ALARMS)
                except ssl.SSLCertVerificationError as e:
                    _LOGGER.error(
                        "Failed to fetch data from {device} due to SSL certificate validation. The {device}({url}) is most likely incompatable Google Home device. Error {error}".format(
                            device=device.device_name, url=url, error=e
                        )
                    )

            else:
                offline_devices.append(device)

            device.timers = timers
            device.alarms = alarms

        # Gives the user a warning if the device is offline, but will not remove entities or device from
        # HA device registry
        if offline_devices:
            for device in offline_devices:
                _LOGGER.warning(
                    "Failed to fetch timers/alarms information from device {device}. Will try again later.".format(
                        device=device.device_name
                    )
                )
        return devices
