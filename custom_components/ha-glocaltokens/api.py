"""Sample API Client."""
import logging
import requests
import json
import aiohttp

from datetime import datetime

from .const import GLOCALTOKENS_ALARMS
from .const import GLOCALTOKENS_TOKEN
from .const import GLOCALTOKENS_TIMERS
from .exceptions import InvalidMasterToken
from glocaltokens.client import GLocalAuthenticationTokens

TIMEOUT = 10


_LOGGER: logging.Logger = logging.getLogger(__package__)

HEADERS = {"Content-type": "application/json; charset=UTF-8"}


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

    def get_google_devices_information(self):

        devices = self._client.get_google_devices_json()

        for x in range(len(devices)):
            #local_token = next(item[GLOCALTOKENS_TOKEN] for item in devices)
            local_token = devices[0][GLOCALTOKENS_TOKEN] # Else x

            url = 'https://IP OF DEVICE:8443/setup/assistant/alarms' # ONLY FOR TESTING PURPOSE - Until we find a way to retrieve ip of each device.
            header = {'cast-local-authorization-token': local_token,
                      'content-type': 'application/json'}

            response = requests.get(url, headers=header, verify=False, timeout=TIMEOUT)

            if response.status_code != 200:
                _LOGGER.error("API returned {}".format(response.status_code))
                #_LOGGER.error(local_token)
                return devices

            result = response.json()

            if GLOCALTOKENS_TIMERS not in result and GLOCALTOKENS_ALARMS not in result:
                _LOGGER.error("API returned unknown json structure")
                return devices

            devices[x][GLOCALTOKENS_TIMERS] = result[GLOCALTOKENS_TIMERS]
            for y in range(len(result[GLOCALTOKENS_TIMERS])):

                timestamp_ms = result[GLOCALTOKENS_TIMERS][y]['fire_time']
                timestamp = timestamp_ms / 1000
                humantime = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
                devices[x][GLOCALTOKENS_TIMERS][y]['date_time'] = humantime

                duration_ms = result[GLOCALTOKENS_TIMERS][y]['original_duration']
                duration = duration_ms / 1000
                humanduration = datetime.utcfromtimestamp(duration).strftime('%H:%M:%S')
                devices[x][GLOCALTOKENS_TIMERS][y]['duration'] = humanduration

            devices[x][GLOCALTOKENS_ALARMS] = result[GLOCALTOKENS_ALARMS]
            for z in range(len(result[GLOCALTOKENS_ALARMS])):

                timestamp_ms = result[GLOCALTOKENS_ALARMS][z]['fire_time']
                timestamp = timestamp_ms / 1000
                humantime = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%dT%H:%M:%S.%fZ%Z')
                localtime = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                devices[x][GLOCALTOKENS_ALARMS][z]['date_time'] = humantime
                devices[x][GLOCALTOKENS_ALARMS][z]['local_time'] = localtime

        return devices
