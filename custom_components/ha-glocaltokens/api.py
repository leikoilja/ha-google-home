"""Sample API Client."""
import logging
import requests
import json
import aiohttp

from datetime import datetime

from .const import API_RETURNED_UNKNOWN
from .const import PORT, ENDPOINT, HEADERS, HEADER_CAST_LOCAL_AUTH
from .const import FIRE_TIME, DATE_TIME, DURATION, ORIGINAL_DURATION, LOCAL_TIME
from .const import SHOW_TIME_ONLY, SHOW_DATE_AND_TIME, SHOW_DATE_TIMEZONE
from .const import GLOCALTOKENS_ALARMS
from .const import GLOCALTOKENS_TOKEN
from .const import GLOCALTOKENS_TIMERS
from .exceptions import InvalidMasterToken
from glocaltokens.client import GLocalAuthenticationTokens
from homeassistant.const import HTTP_OK

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

    def format_timer_information(timer):
        timestamp_ms = timer[FIRE_TIME]
        timestamp = timestamp_ms / 1000
        humantime = datetime.fromtimestamp(timestamp).strftime(SHOW_TIME_ONLY)
        timer[DATE_TIME] = humantime

        duration_ms = timer[ORIGINAL_DURATION]
        duration = duration_ms / 1000
        humanduration = datetime.utcfromtimestamp(duration).strftime(SHOW_TIME_ONLY)
        timer[DURATION] = humanduration
        return timer

    def format_alarm_information(alarm):
        timestamp_ms = alarm[FIRE_TIME]
        timestamp = timestamp_ms / 1000
        humantime = datetime.utcfromtimestamp(timestamp).strftime(SHOW_DATE_TIMEZONE)
        localtime = datetime.fromtimestamp(timestamp).strftime(SHOW_DATE_AND_TIME)
        alarm[DATE_TIME] = humantime
        alarm[LOCAL_TIME] = localtime
        return alarm

    def create_url(ip):
        url = 'https://'+ ip +':'+ str(PORT) + ENDPOINT
        return url

    def get_alarms_and_timers_from(ip, token):

        url = GlocaltokensApiClient.create_url(ip)

        HEADERS[HEADER_CAST_LOCAL_AUTH] = token

        response = requests.get(url, headers=HEADERS, verify=False, timeout=TIMEOUT)

        return response

    def get_google_devices_information(self):

        devices = self._client.get_google_devices_json()

        for x in range(len(devices)):
            #local_token = next(item[GLOCALTOKENS_TOKEN] for item in devices)
            local_token = devices[1][GLOCALTOKENS_TOKEN]

            response = GlocaltokensApiClient.get_alarms_and_timers_from('192.168.0.205', local_token) # IP

            if response.status_code != HTTP_OK:
                _LOGGER.error("API returned {}".format(response.status_code))
                #_LOGGER.error(local_token)
                return devices

            result = response.json()

            if GLOCALTOKENS_TIMERS not in result and GLOCALTOKENS_ALARMS not in result:
                _LOGGER.error(API_RETURNED_UNKNOWN)
                return devices

            devices[x][GLOCALTOKENS_TIMERS] = result[GLOCALTOKENS_TIMERS]
            for y in range(len(result[GLOCALTOKENS_TIMERS])):
                devices[x][GLOCALTOKENS_TIMERS][y] = GlocaltokensApiClient.format_timer_information(result[GLOCALTOKENS_TIMERS][y])

            devices[x][GLOCALTOKENS_ALARMS] = result[GLOCALTOKENS_ALARMS]
            for z in range(len(result[GLOCALTOKENS_ALARMS])):
                devices[x][GLOCALTOKENS_ALARMS][z] = GlocaltokensApiClient.format_timer_information(result[GLOCALTOKENS_ALARMS][z])

        return devices
