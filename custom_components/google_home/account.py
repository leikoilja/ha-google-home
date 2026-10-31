"""The Google account's tokens and device list, and addresses from known hosts."""

import asyncio
from collections.abc import Mapping
from functools import partial
import ipaddress
import logging
from time import monotonic

from aiohttp import ClientError, ClientSession
from glocaltokens.client import Device, GLocalAuthenticationTokens
from glocaltokens.exceptions import AuthenticationError, GLocalTokensError
from glocaltokens.utils.token import is_aas_et
from requests.exceptions import HTTPError, RequestException
from zeroconf import Zeroconf

from homeassistant.core import HomeAssistant

from .const import FETCH_DEVICES_INTERVAL, FETCH_RETRY_DELAYS
from .device_info import async_get_device_info
from .exceptions import InvalidMasterToken
from .mdns import FoundDevices
from .models import GoogleHomeDevice

_LOGGER: logging.Logger = logging.getLogger(__package__)


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


class GoogleAccountClient:
    """The Google account: its tokens, Google's list of its devices, and known hosts."""

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
        """Create the client of a Google account."""
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
        # Google's list is fetched one at a time, and at most once per update of the
        # list: fetches that ended, and how many had ended when the current update
        # started
        self._fetch_lock = asyncio.Lock()
        self._fetches = 0
        self._fetches_before_update = 0
        # The known hosts that the last fetch that ended gave devices, by device ID
        self._known_hosts_found: Mapping[str, str] = {}
        # While the list is unknown, a fetch after a failed one waits a while
        self._fetch_backoff = FetchBackoff()
        # Devices found to have no alarms, timers and settings. They aren't asked for
        # them again until the integration is loaded again, even if Google's list
        # drops them and later lists them again.
        self.unsupported_device_ids: set[str] = set()

    async def async_get_master_token(self) -> str:
        """Get master API token."""
        try:
            master_token = await self.hass.async_add_executor_job(
                self._client.get_master_token
            )
        except AuthenticationError as error:
            raise InvalidMasterToken(str(error)) from error
        if not is_aas_et(master_token):
            raise InvalidMasterToken("Google gave a master token in an unknown format")
        return master_token

    async def async_get_access_token(self) -> str:
        """Get access token using master token."""
        try:
            return await self.hass.async_add_executor_job(self._client.get_access_token)
        except AuthenticationError as error:
            raise InvalidMasterToken(str(error)) from error

    async def async_get_email(self) -> str | None:
        """Return the verified email address of the signed-in account, if Google gives it."""
        try:
            return await self.hass.async_add_executor_job(self._client.get_email)
        except RequestException, AuthenticationError:
            _LOGGER.debug("Failed to get the account's email address", exc_info=True)
            return None

    async def get_android_id(self) -> str:
        """Generate random android_id."""
        return await self.hass.async_add_executor_job(self._client.get_android_id)

    async def async_update_device_list(self) -> Mapping[str, str]:
        """Start an update of Google's device list: fetch it when due, or while it's unknown.

        From here until the next update, whatever asks for Google's list gets it at
        most once: on schedule, when it's unknown, or for a rejected token. Return the
        known hosts, by device ID, that the fetch this update ran or waited for gave
        devices: their info answered then, so their next update needn't ask for it.

        Raise RequestException if Google's sign-in can't be reached while the list is
        unknown.
        """
        self._fetches_before_update = self._fetches
        known_hosts = await self.async_fetch_devices_when_due()
        if not self.google_devices_fetched:
            known_hosts = await self._async_fetch_devices(self._fetches_before_update)
        return known_hosts

    async def _async_fetch_devices(self, fetches: int) -> Mapping[str, str]:
        """Fetch Google's device list, unless a fetch has ended since there were `fetches`.

        A caller that waits while another fetch runs uses that fetch's devices and
        tokens rather than asking Google again. While the list is unknown, nothing
        fetches it until the backoff after a failed fetch has passed: neither the
        update nor a device that rejects its token. With a known list, a rejected
        token still gets a fetch straight away.

        Return the known hosts that this fetch, or the one that ended since there were
        `fetches`, gave devices, by device ID. Only one fetch ends per update, so that's
        the fetch the caller waited for or the one of its update. A later update starts
        from a count that includes it, so it never gets that fetch's hosts.
        """
        async with self._fetch_lock:
            if self._fetches != fetches:
                return self._known_hosts_found
            if not self.google_devices_fetched and self._fetch_backoff.waiting(
                monotonic()
            ):
                _LOGGER.debug("Waiting to fetch Google's device list after it failed")
                return {}
            known_hosts: Mapping[str, str] = {}
            try:
                known_hosts = await self._async_get_devices_from_google()
            finally:
                self._fetches += 1
                # A fetch that failed found none
                self._known_hosts_found = known_hosts
            return known_hosts

    async def _async_get_devices_from_google(self) -> Mapping[str, str]:
        """Ask Google for the device list, and update the devices from it.

        Return the known hosts that this fetch gave devices, by device ID.
        """
        started = monotonic()
        # Whether this works or not, the next scheduled fetch waits a full interval
        self.next_scheduled_fetch = started + FETCH_DEVICES_INTERVAL
        self._fetch_backoff.fetch_started(started)
        fetched_for = self.found_devices.fetch_started()

        try:
            google_devices = await self.hass.async_add_executor_job(
                partial(
                    self._client.get_google_devices,
                    zeroconf_instance=self.zeroconf_instance,
                    force_homegraph_reload=True,
                )
            )
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
            return {}
        self._fetch_backoff.fetch_worked()
        self.sign_in_error = None
        self.google_devices_fetched = True
        self._use_google_devices(google_devices, started)
        self.found_devices.fetch_worked(fetched_for)
        # Known hosts are only asked when mDNS left a device without an address
        if self.known_hosts and any(
            not device.ip_address and device.cloud_device_id
            for device in self.google_devices
        ):
            return await self.async_use_known_hosts()
        return {}

    def _use_google_devices(self, google_devices: list[Device], started: float) -> None:
        """Replace the device list with the one Google gave to the fetch that started then.

        This runs once for each fetch that Google answered with its list, whether the
        update, a device or an action started it, and not for a caller that waited for
        that fetch, an update that didn't fetch, or a fetch that failed.
        """
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

    async def async_fetch_devices_when_due(self) -> Mapping[str, str]:
        """Fetch Google's device list again when it may have changed.

        Every 20 minutes, however often the devices are updated, to find devices
        added in or removed from the Google Home app, and the address of a device
        that was offline at setup. Also soon after mDNS finds a Cast device that the
        list doesn't have. Return the known hosts that the fetch gave devices, by
        device ID.
        """
        # Until the list is known, updates fetch it anyway, as often as the backoff
        # after failed fetches allows
        if not self.google_devices_fetched:
            return {}
        now = monotonic()
        if now >= self.next_scheduled_fetch:
            _LOGGER.debug("Fetching Google's device list again")
        elif (due := self.found_devices.fetch_due()) is not None and now >= due:
            _LOGGER.debug("Fetching Google's device list for devices that mDNS found")
            self.found_devices.last_fetch = now
        else:
            return {}
        try:
            return await self._async_fetch_devices(self._fetches_before_update)
        except RequestException:
            _LOGGER.debug("Failed to fetch Google's device list", exc_info=True)
            return {}

    async def async_use_known_hosts(self) -> dict[str, str]:
        """Give devices that mDNS didn't find the address of the known host they're at.

        Hosts are matched by the ID that Google and the device itself report. In a
        speaker pair, only the leading speaker reports the pair's ID; the other
        reports its own, which Google doesn't list, so it's never used. Return the
        hosts given, by device ID: their info answered 200 just now.
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
        given: dict[str, str] = {}
        for device in self.google_devices:
            if device.ip_address or not device.cloud_device_id:
                continue
            if known_host := hosts_by_id.get(device.cloud_device_id):
                _LOGGER.debug("Found %s at known host %s", device.name, known_host)
                device.ip_address = known_host
                given[device.device_id] = known_host
        return given

    async def _async_get_cloud_device_id(self, host: str) -> str | None:
        """Return Google's ID of the device at a known host."""
        try:
            info = await async_get_device_info(self._session, host)
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
