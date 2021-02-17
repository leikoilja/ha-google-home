"""Sample API Client."""
import logging
import requests
import json
import aiohttp

from .const import API_RETURNED_UNKNOWN
from .const import PORT, API_ENDPOINT_ALARMS, HEADERS, HEADER_CAST_LOCAL_AUTH
from .const import ALARMS, TIMERS, TOKEN, DEVICE_NAME, DEVICE_IP, DEVICE_PORT
from .exceptions import InvalidMasterToken
from glocaltokens.client import GLocalAuthenticationTokens
from homeassistant.const import HTTP_OK

TIMEOUT = 10

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GlocaltokensApiClient:
    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        android_id: str,
    ) -> None:
        """Sample API Client."""
        self._username = username
        self._password = password
        self._session = session
        self._android_id = android_id
        self._client = GLocalAuthenticationTokens(
            username=username, password=password, android_id=android_id
        )

    async def async_get_master_token(self):
        """Get master API token"""
        master_token = self._client.get_master_token()
        if master_token.startswith("aas_et/") is False:
            raise InvalidMasterToken
        return master_token

    def get_google_devices_json(self):
        """Get google device authentication tokens.
        Note this method will fetch necessary access tokens if missing"""
        return self._client.get_google_devices_json()

    def get_android_id(self):
        """Generate random android_id"""
        return self._client.get_android_id()

    def create_url(self, ip, port, api_endpoint):
        url = 'https://{ip}:{port}/{endpoint}'.format(
            ip=ip,
            port=str(PORT),
            endpoint=api_endpoint
        )
        return url

    def get_alarms_and_timers_from(self, device, endpoint):
        url = self.create_url(device.get(DEVICE_IP), device.get(DEVICE_PORT), endpoint)
        _LOGGER.debug("For device {device} - {url}".format(device=device.get(DEVICE_NAME), url=url))
        HEADERS[HEADER_CAST_LOCAL_AUTH] = device.get(TOKEN)
        response = requests.get(url, headers=HEADERS, verify=False, timeout=TIMEOUT) # verify=False is need to avoid SSL security checks. Othervise it will fail to connect

        if response.status_code != HTTP_OK:
            _LOGGER.error("For device {device} - API returned {error}".format(device=device.get(DEVICE_NAME), error=response.status_code))
            return
        else:
            return response.json()

    def get_google_devices_information(self):
        _LOGGER.debug("Fetching data...")
        devices = json.loads(self._client.get_google_devices_json())

        for device in devices:
            # To avoid keyerror's
            timers = []
            alarms = []
            
            result = self.get_alarms_and_timers_from(device, API_ENDPOINT_ALARMS)
            if result:
                timers = result.get(TIMERS)
                alarms = result.get(ALARMS)

                if not timers and not alarms:
                    _LOGGER.error("For device {device} - {error}".format(device=device.get(DEVICE_NAME), error=API_RETURNED_UNKNOWN))

            device.update({
              TIMERS: timers,
              ALARMS: alarms
            })
            _LOGGER.debug(device)

        _LOGGER.debug(devices)
        return devices
