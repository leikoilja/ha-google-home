"""Sample API Client."""
import logging
import requests
import json
import aiohttp

from .utils import convert_from_ms_to_s

from datetime import datetime

from .const import API_RETURNED_UNKNOWN
from .const import PORT, API_ENDPOINT_ALARMS, HEADERS, HEADER_CAST_LOCAL_AUTH
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

    def format_timer_information(self, timer):
        timestamp = convert_from_ms_to_s(timer[FIRE_TIME])
        timer[DATE_TIME] = datetime.fromtimestamp(timestamp).strftime(SHOW_TIME_ONLY)

        duration = convert_from_ms_to_s(timer[ORIGINAL_DURATION])
        timer[DURATION] = datetime.utcfromtimestamp(duration).strftime(SHOW_TIME_ONLY)
        return timer

    def format_alarm_information(self, alarm):
        timestamp = convert_from_ms_to_s(alarm[FIRE_TIME])
        alarm[DATE_TIME] = datetime.utcfromtimestamp(timestamp).strftime(SHOW_DATE_TIMEZONE)
        alarm[LOCAL_TIME] = datetime.fromtimestamp(timestamp).strftime(SHOW_DATE_AND_TIME)
        return alarm

    def create_url(self, ip, api_endpoint):
        url = 'https://{ip}:{port}/{endpoint}'.format(
            ip=ip,
            port=str(PORT),
            endpoint=api_endpoint
        )
        return url

    def get_alarms_and_timers_from(self, ip, token, endpoint):

        url = self.create_url(ip, endpoint)

        HEADERS[HEADER_CAST_LOCAL_AUTH] = token

        response = requests.get(url, headers=HEADERS, verify=False, timeout=TIMEOUT)

        return response

    def get_google_devices_information(self):

        devices = self._client.get_google_devices_json()

        for device in range(len(devices)):
            device_array = devices[1]

            # local_token = device[GLOCALTOKENS_TOKEN]
            local_token = device_array[GLOCALTOKENS_TOKEN] # ONLY BECAUSE WE DONT HAVE DISCOVERY YET - I manuly select device so i can test

            response = self.get_alarms_and_timers_from('192.168.0.205', local_token, API_ENDPOINT_ALARMS) # IP

            if response.status_code != HTTP_OK:
                _LOGGER.error("API returned {}".format(response.status_code))
                return devices

            result = response.json()

            if GLOCALTOKENS_TIMERS not in result and GLOCALTOKENS_ALARMS not in result:
                _LOGGER.error(API_RETURNED_UNKNOWN)
                return devices

            timers = result[GLOCALTOKENS_TIMERS]
            devices[device][GLOCALTOKENS_TIMERS] = [self.format_timer_information(timer) for timer in timers]

            alarms = result[GLOCALTOKENS_ALARMS]
            devices[device][GLOCALTOKENS_ALARMS] = [self.format_alarm_information(alarm) for alarm in alarms]


        return devices
