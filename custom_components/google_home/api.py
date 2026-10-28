"""Sample API Client."""

# The module is due to be split into smaller ones
# pylint: disable=too-many-lines

import asyncio
from http import HTTPStatus
import ipaddress
import json
import logging
from time import monotonic
from typing import Literal, cast

from aiohttp import (
    ClientConnectionError,
    ClientError,
    ClientPayloadError,
    ClientResponse,
    ClientSession,
    ClientTimeout,
)
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError
from glocaltokens.client import Device, GLocalAuthenticationTokens
from glocaltokens.exceptions import AuthenticationError, GLocalTokensError
from glocaltokens.utils.token import is_aas_et
from requests.exceptions import HTTPError, RequestException
from zeroconf import Zeroconf

from homeassistant.core import HomeAssistant

from .const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARM_VOLUME,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DO_NOT_DISTURB,
    API_ENDPOINT_EUREKA_INFO,
    API_ENDPOINT_REBOOT,
    FETCH_DEVICES_INTERVAL,
    FETCH_RETRY_DELAYS,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    JSON_ALARM,
    JSON_ALARM_VOLUME,
    JSON_NOTIFICATIONS_ENABLED,
    JSON_TIMER,
    PORT,
    SUPPORT_CHECK_DELAY,
    TIMEOUT,
)
from .exceptions import (
    AlarmsAndTimersNotDeleted,
    AlarmsAndTimersNotFetched,
    DeviceRequestFailed,
    InvalidMasterToken,
    RequestFailure,
)
from .mdns import FoundDevices
from .models import GoogleHomeDevice
from .types import AlarmJsonDict, JsonDict, TimerJsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


def lacks_assistant(info: dict[str, object] | None) -> bool:
    """Return whether a device's info lists its features without Google Assistant.

    Google and Nest speakers and displays report assistant_supported as true. A
    Chromecast Audio leaves it out of its list, so a missing key counts as no, as
    does false. No list, an empty one, or any other value says nothing either way.
    """
    device_info = info.get("device_info") if info else None
    capabilities = (
        device_info.get("capabilities") if isinstance(device_info, dict) else None
    )
    if not isinstance(capabilities, dict) or not capabilities:
        return False
    # Only the JSON false: 0, null or "false" isn't a clear answer
    return capabilities.get("assistant_supported", False) is False


class FetchBackoff:
    """When Google's device list may be fetched again after fetches fail.

    Each fetch counts as failed from its start until Google answers. After a failure,
    the next fetch waits at least the next of FETCH_RETRY_DELAYS from that start, longer
    for each failure in a row, and a fetch that works starts over. Times are monotonic
    seconds.
    """

    def __init__(self) -> None:
        """Start with no failures."""
        self._failures = 0
        self._retry_at = 0.0

    def fetch_started(self, now: float) -> None:
        """Count a fetch that starts now as failed, until fetch_worked() says otherwise."""
        delay = FETCH_RETRY_DELAYS[min(self._failures, len(FETCH_RETRY_DELAYS) - 1)]
        self._retry_at = now + delay
        self._failures += 1

    def fetch_worked(self) -> None:
        """Forget the failures once Google answers."""
        self._failures = 0
        self._retry_at = 0.0

    def waiting(self, now: float) -> bool:
        """Return whether it's too soon after a failed fetch to fetch again."""
        return now < self._retry_at


def answer_failure(
    device: GoogleHomeDevice, response: ClientResponse
) -> RequestFailure:
    """Log an answer other than 200 from the device, and return why it failed."""
    if response.status == HTTPStatus.UNAUTHORIZED:
        _LOGGER.debug("%s rejected its token", device.name)
        return "token_rejected"
    device.available = False
    if response.status == HTTPStatus.NOT_FOUND:
        _LOGGER.debug(
            (
                "Failed to perform request to %s, API returned %d. "
                "The device(hardware='%s') may be starting, or may "
                "have no alarms/timers."
            ),
            device.name,
            response.status,
            device.hardware,
        )
        return "not_ready"
    _LOGGER.error(
        "Failed to access %s, API returned %d: %s",
        device.name,
        response.status,
        response,
    )
    return "request_failed"


class GlocaltokensApiClient:
    """API client."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        *,
        username: str | None = None,
        password: str | None = None,
        master_token: str | None = None,
        oauth_token: str | None = None,
        android_id: str | None = None,
        zeroconf_instance: Zeroconf | None = None,
        known_hosts: list[str] | None = None,
    ):
        """Sample API Client."""
        self.hass = hass
        self._username = username
        self._password = password
        self._session = session
        self._android_id = android_id
        self._client = GLocalAuthenticationTokens(
            username=username,
            password=password,
            master_token=master_token,
            oauth_token=oauth_token,
            android_id=android_id,
        )
        self.google_devices: list[GoogleHomeDevice] = []
        # Whether google_devices is the list of the last successful fetch, which can
        # be empty. It isn't until a fetch succeeds, or once a device rejects its
        # token and gets no new token that it accepts.
        self.google_devices_fetched = False
        # Why Google last rejected the master token, until a fetch succeeds
        self.sign_in_error: AuthenticationError | None = None
        # Whether setup's first update is running. If Google rejects the master token
        # then, setup fails with Google's reason, which Home Assistant logs.
        self.setting_up = False
        self.zeroconf_instance = zeroconf_instance
        self.known_hosts = known_hosts or []
        # Setup fetches the list straight after creating the client
        self.next_scheduled_fetch = monotonic() + FETCH_DEVICES_INTERVAL
        # The Cast devices that mDNS finds between fetches
        self.found_devices = FoundDevices(self)
        # Google's list is fetched one at a time, and at most once per update:
        # fetches that ended, and how many had ended when the current update started
        self._fetch_lock = asyncio.Lock()
        self._fetches = 0
        self._fetches_before_update = 0
        # Devices found at a known host in the current update. Their info answered 200
        # then, so they aren't asked for it again in that update.
        self._found_at_known_host: set[str] = set()
        # While the list is unknown, a fetch after a failed one waits a while
        self._fetch_backoff = FetchBackoff()
        # Devices found to have no alarms, timers and settings. They aren't asked for
        # them again until the integration is loaded again, even if Google's list
        # drops them and later lists them again.
        self.unsupported_device_ids: set[str] = set()

    async def async_get_master_token(self) -> str:
        """Get master API token."""

        def _get_master_token() -> str:
            return self._client.get_master_token()

        try:
            master_token = await self.hass.async_add_executor_job(_get_master_token)
        except AuthenticationError as error:
            raise InvalidMasterToken(str(error)) from error
        if not is_aas_et(master_token):
            raise InvalidMasterToken("Google gave a master token in an unknown format")
        return master_token

    async def async_get_access_token(self) -> str:
        """Get access token using master token."""

        def _get_access_token() -> str:
            return self._client.get_access_token()

        try:
            return await self.hass.async_add_executor_job(_get_access_token)
        except AuthenticationError as error:
            raise InvalidMasterToken(str(error)) from error

    async def async_get_email(self) -> str | None:
        """Return the verified email address of the signed-in account, if Google gives it."""

        def _get_email() -> str | None:
            return self._client.get_email()

        try:
            return await self.hass.async_add_executor_job(_get_email)
        except RequestException, AuthenticationError:
            _LOGGER.debug("Failed to get the account's email address", exc_info=True)
            return None

    async def get_google_devices(
        self, *, refetch: bool = False
    ) -> list[GoogleHomeDevice]:
        """Get google device authentication tokens.

        Note this method will fetch necessary access tokens if missing.
        """

        if not self.google_devices_fetched or refetch:
            await self._async_fetch_devices(self._fetches_before_update)
        return self.google_devices

    async def _async_fetch_devices(self, fetches: int) -> None:
        """Fetch Google's device list, unless a fetch has ended since there were `fetches`.

        A caller that waits while another fetch runs uses that fetch's devices and
        tokens rather than asking Google again. While the list is unknown, nothing
        fetches it until the backoff after a failed fetch has passed: neither the
        update nor a device that rejects its token. With a known list, a rejected
        token still gets a fetch straight away.
        """
        async with self._fetch_lock:
            if self._fetches != fetches:
                return
            if not self.google_devices_fetched and self._fetch_backoff.waiting(
                monotonic()
            ):
                _LOGGER.debug("Waiting to fetch Google's device list after it failed")
                return
            try:
                await self._async_get_devices_from_google()
            finally:
                self._fetches += 1

    async def _async_get_devices_from_google(self) -> None:
        """Ask Google for the device list, and update the devices from it."""
        started = monotonic()
        # Whether this works or not, the next scheduled fetch waits a full interval
        self.next_scheduled_fetch = started + FETCH_DEVICES_INTERVAL
        self._fetch_backoff.fetch_started(started)
        fetched_for = self.found_devices.fetch_started()

        def _get_google_devices() -> list[Device]:
            return self._client.get_google_devices(
                zeroconf_instance=self.zeroconf_instance,
                force_homegraph_reload=True,
            )

        try:
            google_devices = await self.hass.async_add_executor_job(_get_google_devices)
        # Google rejected the master token, gave no home graph, or answered with
        # a 5xx or 429, which glocaltokens raises as HTTPError
        except (GLocalTokensError, HTTPError) as error:
            log = _LOGGER.error
            # Only signing in again helps when Google rejects the master token.
            # Other errors say nothing about it, so an earlier rejection stays.
            if isinstance(error, AuthenticationError):
                self.sign_in_error = error
                # Setup then fails with Google's reason, which Home Assistant logs
                if self.setting_up:
                    log = _LOGGER.debug
            log("Failed to fetch Google's device list: %s", error)
            # Keep the devices of an earlier fetch rather than drop them
            return
        self._fetch_backoff.fetch_worked()
        self.sign_in_error = None
        self.google_devices_fetched = True
        known_devices = {device.device_id: device for device in self.google_devices}
        self.google_devices = []
        for google_device in google_devices:
            device = GoogleHomeDevice(
                device_id=google_device.device_id,
                name=google_device.device_name,
                auth_token=google_device.local_auth_token,
                ip_address=google_device.ip_address,
                hardware=google_device.hardware,
                cloud_device_id=google_device.cloud_device_id,
            )
            # Prefer an address that mDNS reported while this fetch ran over the fetch's
            # scan, and the scan over an earlier report.
            # ponytail: a report during the fetch wins even if the scan read a newer
            # address, until the next report or fetch
            found_device = self.found_devices.get(device.cloud_device_id)
            if found_device and found_device.reported_at > started:
                device.ip_address = found_device.address
            # Keep a known device's alarms, timers and settings, so a device
            # that doesn't answer this update doesn't lose them
            if known_device := known_devices.get(device.device_id):
                known_device.name = device.name
                known_device.auth_token = device.auth_token
                # mDNS can miss a device that it found before: keep its address
                known_device.ip_address = device.ip_address or known_device.ip_address
                known_device.hardware = device.hardware
                known_device.cloud_device_id = device.cloud_device_id
                device = known_device
            else:
                device.alarms_unsupported = (
                    device.device_id in self.unsupported_device_ids
                )
                # The scan missed a device that mDNS reported before it was listed
                if not device.ip_address and found_device:
                    device.ip_address = found_device.address
            self.google_devices.append(device)
        self.found_devices.fetch_worked(fetched_for)
        # Known hosts are only asked when mDNS left a device without an address
        if self.known_hosts and any(
            not device.ip_address and device.cloud_device_id
            for device in self.google_devices
        ):
            await self.async_use_known_hosts()

    async def async_fetch_devices_when_due(self) -> None:
        """Fetch Google's device list again when it may have changed.

        Every 20 minutes, however often the devices are updated, to find devices
        added in or removed from the Google Home app, and the address of a device
        that was offline at setup. Also soon after mDNS finds a Cast device that the
        list doesn't have.
        """
        # Until the list is known, updates fetch it anyway, as often as the backoff
        # after failed fetches allows
        if not self.google_devices_fetched:
            return
        now = monotonic()
        if now >= self.next_scheduled_fetch:
            _LOGGER.debug("Fetching Google's device list again")
        elif (due := self.found_devices.fetch_due()) is not None and now >= due:
            _LOGGER.debug("Fetching Google's device list for devices that mDNS found")
            self.found_devices.last_fetch = now
        else:
            return
        try:
            await self.get_google_devices(refetch=True)
        except RequestException:
            _LOGGER.debug("Failed to fetch Google's device list", exc_info=True)

    async def async_use_known_hosts(self) -> None:
        """Give devices that mDNS didn't find the address of the known host they're at.

        Hosts are matched by the ID that Google and the device itself report. In a
        speaker pair, only the leading speaker reports the pair's ID; the other
        reports its own, which Google doesn't list, so it's never used.
        """
        # A host that mDNS already gave to a device can't fill in another one
        found = {
            ipaddress.ip_address(device.ip_address)
            for device in self.google_devices
            if device.ip_address
        }
        hosts = [
            host for host in self.known_hosts if ipaddress.ip_address(host) not in found
        ]
        cloud_device_ids = await asyncio.gather(
            *(self._async_get_cloud_device_id(host) for host in hosts)
        )
        hosts_by_id: dict[str, str] = {}
        for host, cloud_device_id in zip(hosts, cloud_device_ids, strict=True):
            if cloud_device_id is not None:
                # As with mDNS, the first host that reports a device is used
                hosts_by_id.setdefault(cloud_device_id, host)
        for device in self.google_devices:
            if device.ip_address or not device.cloud_device_id:
                continue
            if known_host := hosts_by_id.get(device.cloud_device_id):
                _LOGGER.debug("Found %s at known host %s", device.name, known_host)
                device.ip_address = known_host
                self._found_at_known_host.add(device.device_id)

    async def _async_get_device_info(
        self, host: str, device: GoogleHomeDevice | None = None
    ) -> dict[str, object] | None:
        """Return what the device at this host reports about itself.

        Return None if it answers with something else, such as an error page.
        Raise TimeoutError or ClientError if it doesn't answer. With a device, set
        whether it's reachable: whether a 200 came, with its whole body.
        """
        url = self.create_url(host, PORT, API_ENDPOINT_EUREKA_INFO)
        reachable = False
        try:
            async with self._session.get(
                url, timeout=ClientTimeout(total=TIMEOUT)
            ) as response:
                # A device that is starting can answer 404, and an error page
                # isn't its info
                if response.status != HTTPStatus.OK:
                    _LOGGER.debug(
                        "%s answered %d when asked for its info", host, response.status
                    )
                    return None
                try:
                    info = await response.json()
                # An answer that isn't JSON, though it has come whole
                except ContentTypeError, ValueError:
                    _LOGGER.debug(
                        "%s answered, but not with its info", host, exc_info=True
                    )
                    info = None
                reachable = True
        finally:
            if device is not None:
                device.reachable = reachable
        return info if isinstance(info, dict) else None

    async def _async_get_info_status(self, device: GoogleHomeDevice) -> int | None:
        """Return the status of the device's answer when asked for its info, without its token.

        A 200 counts once its body has come, another status as soon as it comes, and
        isn't undone if the answer then breaks off. Return None if no answer comes, for
        example when the session rejects a redirect. Redirects aren't followed. The
        session itself may try once more after a lost connection.
        """
        assert device.ip_address is not None
        url = self.create_url(device.ip_address, PORT, API_ENDPOINT_EUREKA_INFO)
        status: int | None = None
        try:
            async with self._session.get(
                url, timeout=ClientTimeout(total=TIMEOUT), allow_redirects=False
            ) as response:
                if response.status != HTTPStatus.OK:
                    status = response.status
                else:
                    await response.read()
                    status = HTTPStatus.OK
        except ClientError, TimeoutError:
            if status is None:
                _LOGGER.debug(
                    "%s didn't answer when asked for its info",
                    device.name,
                    exc_info=True,
                )
        return status

    async def _async_get_cloud_device_id(self, host: str) -> str | None:
        """Return Google's ID of the device at a known host."""
        try:
            info = await self._async_get_device_info(host)
        except ClientError, TimeoutError:
            _LOGGER.debug("%s didn't answer with its info", host, exc_info=True)
            return None
        if info is None:
            return None
        device_info = info.get("device_info")
        cloud_device_id = (
            device_info.get("cloud_device_id")
            if isinstance(device_info, dict)
            else None
        )
        if not isinstance(cloud_device_id, str) or not cloud_device_id:
            _LOGGER.debug("Known host %s didn't report a device ID", host)
            return None
        _LOGGER.debug("Known host %s is %s", host, info.get("name"))
        return cloud_device_id.lower()

    async def get_android_id(self) -> str:
        """Generate random android_id."""

        def _get_android_id() -> str:
            return self._client.get_android_id()

        return await self.hass.async_add_executor_job(_get_android_id)

    @staticmethod
    def create_url(ip_address: str, port: int, api_endpoint: str) -> str:
        """Create url to endpoint.

        Note: port argument is unused because all request must be done to 8443.
        """
        if isinstance(ipaddress.ip_address(ip_address), ipaddress.IPv6Address):
            ip_address = f"[{ip_address}]"
        return f"https://{ip_address}:{port}/{api_endpoint}"

    async def update_google_devices_information(self) -> list[GoogleHomeDevice]:
        """Retrieve devices from glocaltokens and fetches alarm/timer data from each of the device."""

        # From here until the next update, whatever asks for Google's list gets it
        # at most once: on schedule, when it's unknown, or for a rejected token
        self._fetches_before_update = self._fetches
        self._found_at_known_host.clear()
        await self.async_fetch_devices_when_due()
        devices = await self.get_google_devices()

        # Gives the user a warning if the device is offline
        for device in devices:
            if not device.ip_address and device.available:
                device.available = False
                _LOGGER.debug(
                    (
                        "Failed to fetch timers/alarms information "
                        "from device %s. We could not determine its IP address, "
                        "the device is either offline or is not compatible "
                        "Google Home device. Will try again later."
                    ),
                    device.name,
                )

        await asyncio.gather(
            *[
                self.collect_data_from_endpoints(device)
                for device in devices
                if device.ip_address
                and (device.auth_token or device.alarms_unsupported)
            ]
        )

        return devices

    async def collect_data_from_endpoints(
        self, device: GoogleHomeDevice
    ) -> GoogleHomeDevice:
        """Collect data from different endpoints.

        A device that doesn't answer isn't asked the rest until the next update, so it
        costs two timeouts, for its alarms and its info, not four. A device without
        alarms is asked only for its info, which shows whether it answers. Actions
        don't come here, so they're always sent.

        The device is reachable if its alarms answer 200, or else its info does. When
        the check for alarms asks for its info, or the device was just found at a known
        host, that answer counts, so it isn't asked again.
        """
        found_at_known_host = device.device_id in self._found_at_known_host
        if device.alarms_unsupported:
            status = (
                HTTPStatus.OK
                if found_at_known_host
                else await self._async_get_info_status(device)
            )
            device.reachable = status == HTTPStatus.OK
            device.count_answer(status)
            return device
        device = await self.update_alarms_and_timers(device)
        status = device.statuses.get((API_ENDPOINT_ALARMS, True))
        answered = device.count_answer(status)
        device.reachable = status == HTTPStatus.OK
        try:
            asked_info = await self._async_find_alarms_unsupported(device)
        except ClientError, TimeoutError:
            _LOGGER.debug(
                "%s didn't answer when asked for its info. Will check again in %d "
                "minutes.",
                device.name,
                SUPPORT_CHECK_DELAY // 60,
                exc_info=True,
            )
            return device
        if device.alarms_unsupported:
            return device
        if not device.reachable and not asked_info:
            device.reachable = found_at_known_host or (
                await self._async_get_info_status(device) == HTTPStatus.OK
            )
        if not answered:
            return device
        device = await self.update_alarm_volume(device)
        if (API_ENDPOINT_ALARM_VOLUME, True) not in device.statuses:
            return device
        return await self.update_do_not_disturb(device)

    async def _async_find_alarms_unsupported(self, device: GoogleHomeDevice) -> bool:
        """Find whether the device has turned out to have no alarms, timers and settings.

        Set alarms_unsupported if so. Return whether the device was asked for its
        info, which also sets whether it's reachable.

        Its alarms must answer "not found" at an update, and again at the first
        update at least SUPPORT_CHECK_DELAY later, as a device that is starting
        answers "not found" for a while. Then its info, in that same update, must
        list its features without Google Assistant. Only a 404 counts: a device
        that doesn't answer may be busy or offline.

        Raise TimeoutError or ClientError if the device doesn't answer when asked
        for its info.
        """
        now = monotonic()
        due = device.support_check_at is not None and now >= device.support_check_at
        status = device.statuses.get((API_ENDPOINT_ALARMS, True))
        if status != HTTPStatus.NOT_FOUND:
            if status == HTTPStatus.OK or due:
                device.support_check_at = None
            return False
        if device.support_check_at is None:
            device.support_check_at = now + SUPPORT_CHECK_DELAY
            return False
        if not due:
            return False
        # Unless its info shows that it lacks Google Assistant, check again later,
        # also when it doesn't answer
        device.support_check_at = now + SUPPORT_CHECK_DELAY
        assert device.ip_address is not None
        info = await self._async_get_device_info(device.ip_address, device)
        if not lacks_assistant(info):
            _LOGGER.debug(
                "%s still answers 404 for alarms, but its info doesn't show that it "
                "lacks Google Assistant. Will check again in %d minutes.",
                device.name,
                SUPPORT_CHECK_DELAY // 60,
            )
            return True
        _LOGGER.debug(
            (
                "%s (hardware='%s') still answers 404 for alarms after at least %d "
                "minutes, and its info lists its features without Google Assistant. "
                "It won't be asked for alarms, timers and settings until the "
                "integration is reloaded."
            ),
            device.name,
            device.hardware,
            SUPPORT_CHECK_DELAY // 60,
        )
        device.alarms_unsupported = True
        device.support_check_at = None
        self.unsupported_device_ids.add(device.device_id)
        return True

    async def update_alarms_and_timers(
        self, device: GoogleHomeDevice, *, polling: bool = True
    ) -> GoogleHomeDevice:
        """Fetch timers and alarms from google device.

        Unless polling, raise if they can't be fetched, so an action doesn't
        work from the alarms and timers of the last update.
        """
        try:
            response = await self.request(
                method="GET",
                endpoint=API_ENDPOINT_ALARMS,
                device=device,
                polling=polling,
            )
        except DeviceRequestFailed as error:
            raise AlarmsAndTimersNotFetched(device.name) from error

        if response is not None and JSON_TIMER in response and JSON_ALARM in response:
            device.set_timers(cast(list[TimerJsonDict], response[JSON_TIMER]))
            device.set_alarms(cast(list[AlarmJsonDict], response[JSON_ALARM]))
            _LOGGER.debug(
                "Successfully retrieved alarms and timers from %s. Response: %s",
                device.name,
                response,
            )
            return device
        if response is not None:
            _LOGGER.error(
                (
                    "Failed to parse fetched alarms and timers for device %s - "
                    "API returned unknown json structure. "
                    "Received = %s"
                ),
                device.name,
                response,
            )
        if not polling:
            raise AlarmsAndTimersNotFetched(device.name)
        return device

    async def delete_alarm_or_timer(
        self, device: GoogleHomeDevice, items_to_delete: list[str]
    ) -> None:
        """Delete one or more timers or alarms in a single request.

        Once the device confirms, also remove them from the device's data. Raise
        if it doesn't, as it may still have them.
        """

        if not items_to_delete:
            return

        data = {"ids": items_to_delete}

        item_type = items_to_delete[0].split("/", maxsplit=1)[0]

        _LOGGER.debug(
            "Deleting %s from Google Home device %s - Raw data: %s",
            item_type,
            device.name,
            data,
        )

        try:
            response = await self.request(
                method="POST",
                endpoint=API_ENDPOINT_ALARM_DELETE,
                device=device,
                data=data,
            )
        # A reply that isn't valid JSON, although its content type says it is
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            _LOGGER.error(
                "%s sent a reply that isn't valid JSON: %s", device.name, error
            )
            raise AlarmsAndTimersNotDeleted(device.name) from error
        except DeviceRequestFailed as error:
            raise AlarmsAndTimersNotDeleted(device.name) from error

        # Only this reply is known to confirm a delete
        if isinstance(response, dict) and response.get("success") is True:
            _LOGGER.debug("Successfully deleted %s for %s", item_type, device.name)
            device.remove_alarms_and_timers(items_to_delete)
            return
        if response is not None:
            _LOGGER.error(
                "%s didn't confirm the %s delete. Received = %s",
                device.name,
                item_type,
                response,
            )
        raise AlarmsAndTimersNotDeleted(device.name)

    async def reboot_google_device(self, device: GoogleHomeDevice) -> None:
        """Reboot a Google Home device if it supports this.

        Raise DeviceRequestFailed if it doesn't answer 200. The rest of its answer
        isn't read, as it may go down while sending it.
        """

        # "now" means reboot and "fdr" means factory reset (Not implemented).
        data = {"params": "now"}

        _LOGGER.debug(
            "Trying to reboot Google Home device %s",
            device.name,
        )

        await self.request(
            method="POST",
            endpoint=API_ENDPOINT_REBOOT,
            device=device,
            data=data,
            read_reply=False,
        )
        # It answers so even if the device does not support rebooting.
        _LOGGER.info(
            "Successfully asked %s to reboot.",
            device.name,
        )

    async def update_do_not_disturb(
        self, device: GoogleHomeDevice, enable: bool | None = None
    ) -> GoogleHomeDevice:
        """Get or set the do not disturb setting on a Google Home device.

        Raise DeviceRequestFailed if setting it fails.
        """

        data = None
        polling = False

        if enable is not None:
            # Setting is inverted on device
            data = {JSON_NOTIFICATIONS_ENABLED: not enable}
            _LOGGER.debug(
                "Setting Do Not Disturb setting to %s on Google Home device %s",
                enable,
                device.name,
            )
        else:
            polling = True
            _LOGGER.debug(
                "Getting Do Not Disturb setting from Google Home device %s",
                device.name,
            )

        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_DO_NOT_DISTURB,
            device=device,
            data=data,
            polling=polling,
        )
        if response is not None:
            if JSON_NOTIFICATIONS_ENABLED in response:
                enabled = not bool(response[JSON_NOTIFICATIONS_ENABLED])
                _LOGGER.debug(
                    "Received Do Not Disturb setting from Google Home device %s"
                    " - Enabled: %s",
                    device.name,
                    enabled,
                )

                device.set_do_not_disturb(enabled)
            else:
                _LOGGER.debug(
                    (
                        "Unexpected response from Google Home device '%s' "
                        "when fetching DND status - %s"
                    ),
                    device.name,
                    response,
                )

        return device

    async def update_alarm_volume(
        self, device: GoogleHomeDevice, volume: int | None = None
    ) -> GoogleHomeDevice:
        """Get or set the alarm volume setting on a Google Home device.

        Raise DeviceRequestFailed if setting it fails.
        """

        data: JsonDict | None = None
        polling = False

        if volume is not None:
            # Setting is inverted on device
            volume_float = volume / 100
            data = {JSON_ALARM_VOLUME: volume_float}
            _LOGGER.debug(
                "Setting alarm volume to %d(float=%f) on Google Home device %s",
                volume,
                volume_float,
                device.name,
            )
        else:
            polling = True
            _LOGGER.debug(
                "Getting alarm volume from Google Home device %s",
                device.name,
            )

        response = await self.request(
            method="POST",
            endpoint=API_ENDPOINT_ALARM_VOLUME,
            device=device,
            data=data,
            polling=polling,
        )
        if response:
            if JSON_ALARM_VOLUME in response:
                if polling:
                    volume_raw = str(response[JSON_ALARM_VOLUME])
                    volume = round(float(volume_raw) * 100)
                    _LOGGER.debug(
                        "Received alarm volume from Google Home device %s"
                        " - Volume: %d(raw=%s)",
                        device.name,
                        volume,
                        volume_raw,
                    )
                else:
                    assert volume is not None
                    _LOGGER.debug(
                        "Successfully set alarm volume to %d on Google Home device %s",
                        volume,
                        device.name,
                    )
                device.set_alarm_volume(volume)
            else:
                _LOGGER.debug(
                    (
                        "Unexpected response from Google Home device '%s' "
                        "when fetching alarm volume setting - %s"
                    ),
                    device.name,
                    response,
                )

        return device

    async def request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        device: GoogleHomeDevice,
        data: JsonDict | None = None,
        polling: bool = False,
        *,
        read_reply: bool = True,
    ) -> JsonDict | None:
        """Shared request method.

        Unless polling, raise DeviceRequestFailed when the device doesn't answer
        200 or its answer can't be read. An update only logs it, and gets None.
        Without read_reply, the 200 is the whole answer: the rest isn't read, and
        {} is returned.
        """
        try:
            return await self._send(
                method, endpoint, device, data, polling, read_reply=read_reply
            )
        except DeviceRequestFailed:
            if polling:
                return None
            raise

    async def _send(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        device: GoogleHomeDevice,
        data: JsonDict | None,
        polling: bool,
        *,
        read_reply: bool,
        retry: bool = True,
    ) -> JsonDict | None:
        """Send a request and return the answer, or raise DeviceRequestFailed.

        If the device rejects its token, get a new one and send the request once
        more. Only a rejection is retried: a request that timed out may have run.
        """

        # A request sent again with a new token replaces the status
        device.statuses.pop((endpoint, polling), None)

        if device.ip_address is None:
            _LOGGER.warning("Device %s doesn't have an IP address!", device.name)
            raise DeviceRequestFailed(device.name, "offline")

        if (token := device.auth_token) is None:
            _LOGGER.warning("Device %s doesn't have an auth token!", device.name)
            raise DeviceRequestFailed(device.name, "request_failed")

        url = self.create_url(device.ip_address, PORT, endpoint)

        headers: dict[str, str] = {
            HEADER_CAST_LOCAL_AUTH: token,
            HEADER_CONTENT_TYPE: "application/json",
        }

        _LOGGER.debug(
            "Requesting endpoint %s for Google Home device %s - %s",
            endpoint,
            device.name,
            url,
        )

        resp = None
        failure: RequestFailure | None = None

        try:
            timeout = ClientTimeout(total=TIMEOUT)
            async with self._session.request(
                method, url, json=data, headers=headers, timeout=timeout
            ) as response:
                status = response.status
                if response.status == HTTPStatus.OK:
                    try:
                        # Without read_reply, what comes after the status, or
                        # doesn't, can't undo it
                        resp = await response.json() if read_reply else {}
                    except ContentTypeError:
                        resp = {}
                    device.available = True
                else:
                    failure = answer_failure(device, response)
            # Only once the answer has been read, if it's read: a 200 whose body
            # times out or is cut off isn't an answer
            device.statuses[endpoint, polling] = status
        except ClientConnectorError as error:
            logger_func = _LOGGER.debug if polling else _LOGGER.warning
            logger_func(
                "Failed to connect to %s device. The device is probably offline.",
                device.name,
            )
            device.available = False
            raise DeviceRequestFailed(device.name, "offline") from error
        except ClientError as error:
            # Make sure that we log the exception from the client if one occurred.
            _LOGGER.exception(
                "Request from %s device error",
                device.name,
            )
            device.available = False
            # A connection that closed or an answer that was cut off: the device
            # may have done it
            if isinstance(error, ClientConnectionError | ClientPayloadError):
                raise DeviceRequestFailed(device.name, "no_reply") from error
            raise DeviceRequestFailed(device.name, "request_failed") from error
        except TimeoutError as error:
            _LOGGER.debug(
                "%s device timed out while performing a request to it - Raw data: %s",
                device.name,
                data,
            )
            device.available = False
            raise DeviceRequestFailed(device.name, "no_reply") from error

        if failure == "token_rejected":
            if retry and await self._async_get_new_token(device, token):
                _LOGGER.debug(
                    "Sending the request to %s again with its new token", device.name
                )
                return await self._send(
                    method,
                    endpoint,
                    device,
                    data,
                    polling,
                    read_reply=read_reply,
                    retry=False,
                )
            self._mark_token_rejected(device, polling=polling)
        if failure is not None:
            raise DeviceRequestFailed(device.name, failure)
        return resp

    def _mark_token_rejected(self, device: GoogleHomeDevice, *, polling: bool) -> None:
        """Mark a device that rejected its token, with no new one to try."""
        if polling:
            _LOGGER.debug(
                (
                    "Failed to fetch data from %s due to invalid token. "
                    "Will refresh the token and try again."
                ),
                device.name,
            )
        else:
            _LOGGER.warning(
                "Failed to send the request to %s due to invalid token. "
                "Token will be refreshed, please try again later.",
                device.name,
            )
        # Fetch Google's list, with new tokens, at the next update or, after a failed
        # fetch, at the first update once the backoff has passed. Keep the devices
        # meanwhile, so the fetch keeps their data, and the others still update if
        # Google can't be reached.
        self.google_devices_fetched = False
        device.available = False

    async def _async_get_new_token(
        self, device: GoogleHomeDevice, rejected_token: str
    ) -> bool:
        """Return whether a device that rejected its token has a new one now.

        If no fetch since the request was sent has brought one, fetch Google's list.
        Only one fetch runs from one update to the next, so once it has, the device
        waits for the next update. While the list is unknown, it also waits for the
        backoff after a failed fetch.
        """
        if device.auth_token == rejected_token:
            try:
                await self._async_fetch_devices(self._fetches_before_update)
            except RequestException:
                _LOGGER.debug("Failed to fetch Google's device list", exc_info=True)
        return device.auth_token != rejected_token
