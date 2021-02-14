"""Sample API Client."""
import logging
import requests
import json
import aiohttp

from .const import API_RETURNED_UNKNOWN
from .const import PORT, API_ENDPOINT_ALARMS, HEADERS, HEADER_CAST_LOCAL_AUTH
from .const import ALARMS, TIMERS, TOKEN, DEVICE_NAME
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
        return self._client._get_android_id()

    def create_url(self, ip, port, api_endpoint):
        url = 'https://{ip}:{port}/{endpoint}'.format(
            ip=ip,
            port=port,
            endpoint=api_endpoint
        )
        return url

    def get_alarms_and_timers_from(self, ip, port, token, endpoint):
        url = self.create_url(ip, port, endpoint)
        HEADERS[HEADER_CAST_LOCAL_AUTH] = token
        response = requests.get(url, headers=HEADERS, verify=False, timeout=TIMEOUT) # verify=False is need to avoid SSL security checks. Othervise it will fail to connect

        return response

    def get_google_devices_information(self):

        devices = self._client.get_google_devices_json()

        for device in devices:
            # To avoid keyerror's
            device[TIMERS] = []
            device[ALARMS] = []

            ip = '192.168.0.205'
            port = str(PORT)
            token = device[TOKEN]
            response = self.get_alarms_and_timers_from(ip, port, token, API_ENDPOINT_ALARMS) # IP

            if response.status_code != HTTP_OK:
                _LOGGER.error("For device {device} - API returned {error}".format(device=device[DEVICE_NAME], error=response.status_code))
                continue

            result = response.json()

            if TIMERS not in result and ALARMS not in result:
                _LOGGER.error("For device {device} - {error}".format(device=device[DEVICE_NAME], error=API_RETURNED_UNKNOWN))
                continue

            device.update(result)
            _LOGGER.debug(device)

        _LOGGER.debug(devices)
        return devices
