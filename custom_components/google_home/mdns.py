"""Find Google Cast devices with mDNS between fetches of Google's device list."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import ipaddress
import logging
from time import monotonic
from typing import TYPE_CHECKING, NamedTuple

from glocaltokens.const import GOOGLE_CAST_GROUP
from glocaltokens.scanner import CastListener
from zeroconf import BadTypeInNameException, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    CAST_LOOKUP_TIMEOUT,
    CAST_SERVICE_TYPE,
    FOUND_DEVICE_FETCH_DELAY,
    FOUND_DEVICE_FETCH_GAP,
)
from .types import GoogleHomeConfigEntry

if TYPE_CHECKING:
    from .api import GlocaltokensApiClient

_LOGGER: logging.Logger = logging.getLogger(__package__)


class FoundDevice(NamedTuple):
    """A Cast device that mDNS reported, by the name it announces."""

    name: str
    address: str
    reported_at: float
    first_reported_at: float


class FoundDevices:
    """The Cast devices that mDNS found, and the fetches of Google's list for them.

    A device in Google's list gets the address it announces at once, and is asked at
    the next update, without asking Google. A device that the list doesn't have makes
    it be fetched soon, as it may have just been added in the Google Home app.
    """

    def __init__(self, client: GlocaltokensApiClient) -> None:
        """Keep the client whose devices get the addresses."""
        self._client = client
        # By Google's ID. mDNS reports cached devices as soon as setup starts
        # listening, so this exists before that.
        self._devices: dict[str, FoundDevice] = {}
        # IDs that need no fetch of their own: a fetch started after mDNS reported them
        self._covered_ids: set[str] = set()
        # Google's IDs in the list of the last fetch that worked
        self._listed: set[str] = set()
        # Whether the last fetch failed, or a fetch is waiting for Google's list. Found
        # devices then wait for the scheduled retry, or for the list.
        self._fetch_failed = False
        # When the last fetch for found devices started
        self.last_fetch: float | None = None
        # When the next fetch for found devices is due, and the cancel of its timer
        self._timer: tuple[float, CALLBACK_TYPE] | None = None
        # The update that the timer started, until a fetch starts, and while it runs
        self._update_requested = False
        self._update: asyncio.Task[None] | None = None
        # Set once the entry unloads, so nothing starts a fetch for found devices again
        self._stopped = False
        # Runs an update of the devices; setup sets it
        self.request_update: Callable[[], Awaitable[None]] | None = None

    def get(self, cloud_device_id: str | None) -> FoundDevice | None:
        """Return what mDNS last reported about the device with this ID."""
        return self._devices.get(cloud_device_id or "")

    @callback
    def async_device_found(self, cloud_device_id: str, name: str, address: str) -> None:
        """Note a Cast device that mDNS found, with Google's ID for it."""
        now = monotonic()
        earlier = self._devices.get(cloud_device_id)
        self._devices[cloud_device_id] = FoundDevice(
            name, address, now, earlier.first_reported_at if earlier else now
        )
        listed = [
            device
            for device in self._client.google_devices
            if device.cloud_device_id == cloud_device_id
        ]
        for device in listed:
            if device.ip_address != address:
                _LOGGER.debug("mDNS found %s at %s", device.name, address)
                device.ip_address = address
        # A listed device needs no fetch. If a fetch that is running drops it, Google
        # removed it, and the fetch forgets this report.
        if not listed and earlier is None:
            # Until a fetch has worked, the list may just not be known yet
            if self._client.google_devices_fetched:
                _LOGGER.debug(
                    "mDNS found %s at %s, which isn't in Google's device list",
                    name,
                    address,
                )
            else:
                _LOGGER.debug("mDNS found %s at %s", name, address)
        self._schedule()

    @callback
    def async_stop(self) -> None:
        """Stop fetching the list for devices that mDNS finds, as the entry unloads.

        It's for good: cancelling the update runs its cleanup, which mustn't set a
        timer again. Loading the entry again creates a new client.
        """
        self._stopped = True
        self._schedule()
        if self._update:
            self._update.cancel()

    def fetch_started(self) -> set[str]:
        """Note that a fetch of Google's list starts, and return the found IDs it's for.

        It answers for every device that mDNS has found so far, so none of them causes
        a fetch of its own any more, except one that a later list drops. Devices found
        from now on can.
        """
        fetched_for = self._ids_to_fetch()
        self._covered_ids.update(self._devices)
        self._update_requested = False
        # Until it works: if it fails, found devices wait for the scheduled retry
        self._fetch_failed = True
        self._schedule()
        return fetched_for

    def fetch_worked(self, fetched_for: set[str]) -> None:
        """Note that the fetch worked, as soon as the client has its new list.

        Reports from then on count as after the fetch.
        """
        self._fetch_failed = False
        listed = {
            device.cloud_device_id
            for device in self._client.google_devices
            if device.cloud_device_id
        }
        for cloud_device_id in fetched_for - listed:
            _LOGGER.debug(
                "Google's device list doesn't have %s, which mDNS found",
                self._devices[cloud_device_id].name,
            )
        # A device that Google removed may be added again with the same ID, so the
        # next report of it is a first report, as for a new device. Only this list
        # shows the removal, so reports until now are forgotten with it, even from a
        # device set up again meanwhile, which gets its fetch after its next report.
        for cloud_device_id in self._listed - listed:
            self._devices.pop(cloud_device_id, None)
            self._covered_ids.discard(cloud_device_id)
        self._listed = listed
        self._schedule()

    def _ids_to_fetch(self) -> set[str]:
        """Return the IDs of found devices that need a fetch: not listed, not covered."""
        listed = {device.cloud_device_id for device in self._client.google_devices}
        return self._devices.keys() - self._covered_ids - listed

    def fetch_due(self) -> float | None:
        """Return when to fetch Google's list for devices that mDNS found, if at all.

        After the delay from the first report of such a device, which is after the last
        fetch started, as that fetch covered every device found before it. Not until
        the gap after the last such fetch has passed. Not while the list is unknown,
        when every update fetches it, or after a failed fetch, which is retried as
        scheduled.
        """
        if not self._client.google_devices_fetched or self._fetch_failed:
            return None
        if not (ids := self._ids_to_fetch()):
            return None
        due = FOUND_DEVICE_FETCH_DELAY + min(
            self._devices[cloud_device_id].first_reported_at for cloud_device_id in ids
        )
        if self.last_fetch is not None:
            due = max(due, self.last_fetch + FOUND_DEVICE_FETCH_GAP)
        return due

    @property
    def _blocked(self) -> bool:
        """Return whether no timer may ask for an update for found devices now.

        Not after the entry unloads, nor while an update that the timer started hasn't
        fetched yet or still runs: it owns the work, and a fetch has to start before
        another update is asked for.
        """
        return self._stopped or self._update_requested or self._update is not None

    @callback
    def _schedule(self) -> None:
        """Set the timer for the next fetch for found devices, or cancel it."""
        due = None if self._blocked else self.fetch_due()
        if self._timer:
            if self._timer[0] == due:
                return
            self._timer[1]()
            self._timer = None
        if due is None:
            return
        delay = max(0.0, due - monotonic())
        _LOGGER.debug(
            "Fetching Google's device list in %.0f seconds for devices that mDNS found",
            delay,
        )
        self._timer = (
            due,
            async_call_later(self._client.hass, delay, self._async_fetch_due),
        )

    @callback
    def _async_fetch_due(self, _now: datetime) -> None:
        """Update the devices, which fetches the list for the devices that mDNS found.

        Home Assistant's requested refresh can be dropped while an update runs, so
        the update waits for it instead.
        """
        self._timer = None
        due = self.fetch_due()
        if self._blocked or due is None or monotonic() < due:
            self._schedule()
            return
        self._update_requested = True
        self._update = self._client.hass.async_create_background_task(
            self._async_update(),
            "Update Google Home devices for devices that mDNS found",
            eager_start=False,
        )

    async def _async_update(self) -> None:
        """Run one update, then set the timer for devices found meanwhile."""
        try:
            if self.request_update is not None:
                await self.request_update()
        finally:
            self._update = None
            self._schedule()


def cast_device_found(info: AsyncServiceInfo) -> tuple[str, str, str] | None:
    """Return Google's ID, the name and the address of a Cast device that mDNS found.

    None for a Cast group, or a device without an ID or an address that can be
    used: IPv4, or IPv6 that isn't link-local, as glocaltokens' scan uses.
    """
    cloud_device_id = CastListener.get_service_value(info, "cd")
    if not cloud_device_id or (
        CastListener.get_service_value(info, "md") == GOOGLE_CAST_GROUP
    ):
        return None
    # zeroconf lists IPv4 addresses first
    for address in info.parsed_addresses():
        ip_address = ipaddress.ip_address(address)
        if ip_address.version == 4 or not ip_address.is_link_local:
            name = CastListener.get_service_value(info, "fn") or info.name
            return cloud_device_id.lower(), name, address
    return None


@callback
def async_browse_cast_devices(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    zeroconf_instance: Zeroconf,
    found_devices: FoundDevices,
) -> None:
    """Report each Cast device that mDNS finds while the entry is loaded.

    A device that goes offline keeps its address, as it does when a fetch's scan
    misses it: its requests fail until it's found again.
    """

    @callback
    def report(info: AsyncServiceInfo) -> None:
        if found := cast_device_found(info):
            found_devices.async_device_found(*found)

    async def async_look_up(info: AsyncServiceInfo) -> None:
        await info.async_request(zeroconf_instance, CAST_LOOKUP_TIMEOUT)
        report(info)

    @callback
    def on_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        try:
            info = AsyncServiceInfo(service_type, name)
        # Some devices announce a name that isn't valid
        except BadTypeInNameException:
            _LOGGER.debug("Ignored the invalid mDNS name %s", name)
            return
        if info.load_from_cache(zeroconf):
            report(info)
        else:
            entry.async_create_background_task(
                hass, async_look_up(info), f"Look up {name} with mDNS"
            )

    # It reports the devices already in the cache before it returns
    browser = AsyncServiceBrowser(
        zeroconf_instance, [CAST_SERVICE_TYPE], handlers=[on_change]
    )
    entry.async_on_unload(browser.async_cancel)
