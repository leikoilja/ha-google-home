"""Sample API Client."""
import logging

import aiohttp
import requests
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

    def get_google_devices(self):
        """Get google device authentication tokens.
        Note this method will fetch necessary access tokens if missing"""
        return self._client.get_google_devices(disable_discovery=True)

    def get_android_id(self):
        """Generate random android_id"""
        return self._client.get_android_id()

    @staticmethod
    def create_url(ip, port, api_endpoint):
        """Creates url to endpoint.
        Note: port argument is unused because all request must be done to 8443"""
        url = "https://{ip}:{port}/{endpoint}".format(
            ip=ip, port=str(port), endpoint=api_endpoint
        )
        return url

    def get_alarms_and_timers_from(self, device, endpoint):
        """Fetches timers and alarms from google device"""
        url = self.create_url(device.ip, PORT, endpoint)
        _LOGGER.debug(
            "For device {device} - {url}".format(device=device.device_name, url=url)
        )
        # verify=False is need to avoid SSL security checks. Otherwise it will fail to connect"""
        HEADERS[HEADER_CAST_LOCAL_AUTH] = device.local_auth_token
        response = requests.get(url, headers=HEADERS, verify=False, timeout=TIMEOUT)

        if response.status_code != HTTP_OK:
            _LOGGER.error(
                "For device {device} - API returned {error}: {reason}".format(
                    device=device.device_name,
                    error=response.status_code,
                    reason=response.text,
                )
            )
            return
        else:
            return response.json()

    def get_google_devices_information(self):
        """Retrieves devices from glocaltokens"""
        _LOGGER.debug("Fetching data...")
        offline_devices = []
        devices = self.get_google_devices()

        for device in devices:
            # To avoid key error's
            timers = []
            alarms = []
            if device.ip:
                result_json = self.get_alarms_and_timers_from(
                    device, API_ENDPOINT_ALARMS
                )
                if result_json:
                    timers = result_json.get(TIMERS)
                    alarms = result_json.get(ALARMS)

                    if not timers and not alarms:
                        _LOGGER.error(
                            "For device {device} - {error}".format(
                                device=device.device_name, error=API_RETURNED_UNKNOWN
                            )
                        )
            else:
                offline_devices.append(device)
                device.timers = timers
                device.alarms = alarms

            _LOGGER.debug(device)

        # Gives the user a warning if the device is offline, but will not remove entities or device from
        # HA device registry
        if offline_devices:
            for device in offline_devices:
                _LOGGER.warning(
                    "Failed to fetch timers/alarms information from device {device}. Will try again later.".format(
                        device=device.device_name
                    )
                )
        _LOGGER.debug(devices)
        return devices
