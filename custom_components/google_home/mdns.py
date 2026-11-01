"""Find Google Cast devices with mDNS, for the devices in Google's list and new ones."""

import asyncio
from collections.abc import Awaitable, Callable, KeysView
from datetime import datetime
import ipaddress
import logging
from time import monotonic
from typing import TYPE_CHECKING, NamedTuple

from zeroconf import BadTypeInNameException, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    CAST_GROUP_MODEL,
    CAST_LOOKUP_TIMEOUT,
    CAST_SERVICE_TYPE,
    CAST_SETUP_WAIT,
    FOUND_DEVICE_FETCH_DELAY,
    FOUND_DEVICE_FETCH_GAP,
)
from .types import GoogleHomeConfigEntry

if TYPE_CHECKING:
    from .account import GoogleAccountClient

_LOGGER: logging.Logger = logging.getLogger(__package__)


class FoundDevice(NamedTuple):
    """A Cast device that mDNS reported, by the name it announces."""

    name: str
    address: str
    first_reported_at: float


class FoundDevices:
    """The Cast devices that mDNS found, and the fetches of Google's list for them.

    A device in Google's list gets the address it announces at once, and is asked at
    the next update, without asking Google. A device that the list doesn't have makes
    it be fetched soon, as it may have just been added in the Google Home app.
    """

    def __init__(self, client: GoogleAccountClient) -> None:
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
        # Runs an update of Google's device list; setup sets it
        self.request_update: Callable[[], Awaitable[None]] | None = None
        # Starts browsing for Cast devices again; setup sets it
        self.browse_again: Callable[[], Awaitable[None]] | None = None
        # While setup waits for addresses, done when mDNS reports a device
        self._reported: asyncio.Future[None] | None = None

    def get(self, cloud_device_id: str | None) -> FoundDevice | None:
        """Return what mDNS last reported about the device with this ID."""
        return self._devices.get(cloud_device_id or "")

    @property
    def cloud_device_ids(self) -> KeysView[str]:
        """Return Google's IDs of the devices that mDNS reported, except forgotten ones.

        A fetch forgets a device's reports when Google's list drops it.
        """
        return self._devices.keys()

    @callback
    def async_device_found(
        self, cloud_device_id: str, name: str, address: str, *, replayed: bool = False
    ) -> None:
        """Note a Cast device that mDNS found, with Google's ID for it.

        A replayed report is of a device that was already in the cache when browsing
        started again. It gives a device in Google's list its address, but isn't news
        of any other device, such as one that an earlier list dropped.
        """
        listed = [
            device
            for device in self._client.google_devices
            if device.cloud_device_id == cloud_device_id
        ]
        if replayed and not listed:
            return
        now = monotonic()
        earlier = self._devices.get(cloud_device_id)
        self._devices[cloud_device_id] = FoundDevice(
            name, address, earlier.first_reported_at if earlier else now
        )
        if self._reported is not None and not self._reported.done():
            self._reported.set_result(None)
        for device in listed:
            if device.ip_address != address:
                _LOGGER.debug("mDNS found %s at %s", device.name, address)
                device.ip_address = address
        # A listed device needs no fetch. If a fetch that is running drops it, Google
        # removed it, and the fetch forgets this report.
        if not listed and earlier is None:
            if cloud_device_id in self._client.excluded_cloud_device_ids:
                _LOGGER.debug(
                    "mDNS found %s at %s, which is in a home whose devices aren't added",
                    name,
                    address,
                )
            # Until a fetch has worked, the list may just not be known yet
            elif self._client.google_devices_fetched:
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
        """Stop fetching the list for devices that mDNS finds.

        As the entry unloads, or at setup while polling is off. It's for good:
        cancelling the update runs its cleanup, which mustn't set a timer again.
        Loading the entry again creates a new client. Found devices still get their
        addresses.
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
        for cloud_device_id in (
            fetched_for - listed - self._client.excluded_cloud_device_ids
        ):
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

    async def async_browse_again(self) -> None:
        """Browse for Cast devices again after a fetch of Google's list.

        The new browser replays the cache and asks the network, which finds a device
        that came back, perhaps at another address, without an announcement that Home
        Assistant received.
        """
        if self.browse_again is not None:
            await self.browse_again()

    async def async_wait_for_addresses(self) -> None:
        """Wait until mDNS gives each device in Google's list an address, for a while.

        At most CAST_SETUP_WAIT seconds, so that setup asks a device that mDNS finds
        just after Google's list arrived at its address. A device without Google's
        other ID for it can't be found, so it isn't waited for. A timeout would end the
        wait by cancelling setup's task, and Home Assistant's async_block_till_done
        doesn't wait for a task that is being cancelled.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CAST_SETUP_WAIT
        try:
            while (
                self._client.missing_addresses
                and (remaining := deadline - loop.time()) > 0
            ):
                self._reported = loop.create_future()
                await asyncio.wait([self._reported], timeout=remaining)
        finally:
            self._reported = None

    def _ids_to_fetch(self) -> set[str]:
        """Return the IDs of found devices that need a fetch: not listed, not covered.

        Nor in a home whose devices aren't added, which the list never has.
        """
        listed = {device.cloud_device_id for device in self._client.google_devices}
        return (
            self._devices.keys()
            - self._covered_ids
            - listed
            - self._client.excluded_cloud_device_ids
        )

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
        """Update Google's device list, which fetches it for the devices that mDNS found.

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
            "Update Google's device list for devices that mDNS found",
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


def txt_value(info: AsyncServiceInfo, key: str) -> str | None:
    """Return the value of a key in a service's TXT record, if it's there and UTF-8.

    zeroconf gives the values as bytes, also of a service created with str values.
    """
    if (value := info.properties.get(key.encode())) is None:
        return None
    try:
        return value.decode()
    except UnicodeDecodeError:
        _LOGGER.debug("Service %s has an invalid %s value", info.name, key)
        return None


def cast_device_found(info: AsyncServiceInfo) -> tuple[str, str, str] | None:
    """Return Google's ID, the name and the address of a Cast device that mDNS found.

    None for a Cast group, or a device without an ID or an address that can be
    used: IPv4, or IPv6 that isn't link-local, which needs its interface.
    """
    cloud_device_id = txt_value(info, "cd")
    if not cloud_device_id or txt_value(info, "md") == CAST_GROUP_MODEL:
        return None
    # zeroconf lists IPv4 addresses first
    for address in info.parsed_addresses():
        ip_address = ipaddress.ip_address(address)
        if ip_address.version == 4 or not ip_address.is_link_local:
            name = txt_value(info, "fn") or info.name
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

    A device that goes offline keeps its address: its requests fail until it's found
    again. One browser runs at a time; browsing again replaces it.
    """
    # The services whose PTR record a browser has reported as added, until one reports
    # it as removed when it expires. A browser that starts reports the PTR records
    # already in the cache as added, so a service added again while it's here is
    # replayed from the cache. Its other records can come first, as an update, so an
    # update doesn't add it.
    cached: set[str] = set()
    browser: AsyncServiceBrowser | None = None
    unloaded = False

    @callback
    def report(info: AsyncServiceInfo, replayed: bool) -> None:
        if found := cast_device_found(info):
            found_devices.async_device_found(*found, replayed=replayed)

    async def async_look_up(
        info: AsyncServiceInfo, service_type: str, name: str, replayed: bool
    ) -> None:
        await info.async_request(zeroconf_instance, CAST_LOOKUP_TIMEOUT)
        # The lookup keeps an address that expired while it waited, which may be
        # one that a newer report replaced, so report what the cache has now. By
        # the name that the browser reported: loading records can change the case
        # of the info's name to theirs, which then doesn't match the type.
        current = AsyncServiceInfo(service_type, name)
        current.load_from_cache(zeroconf_instance)
        report(current, replayed)

    @callback
    def on_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            cached.discard(name)
            return
        try:
            info = AsyncServiceInfo(service_type, name)
        # Some devices announce a name that isn't valid
        except BadTypeInNameException:
            _LOGGER.debug("Ignored the invalid mDNS name %s", name)
            return
        replayed = False
        if state_change is ServiceStateChange.Added:
            replayed = name in cached
            cached.add(name)
        if info.load_from_cache(zeroconf):
            report(info, replayed)
        else:
            entry.async_create_background_task(
                hass,
                async_look_up(info, service_type, name, replayed),
                f"Look up {name} with mDNS",
            )

    @callback
    def browse() -> None:
        nonlocal browser
        # It reports the devices already in the cache before it returns
        browser = AsyncServiceBrowser(
            zeroconf_instance, [CAST_SERVICE_TYPE], handlers=[on_change]
        )

    # Each browser is cancelled once, also if the entry unloads while browsing again
    async def async_browse_again() -> None:
        nonlocal browser
        if (stopping := browser) is None:
            return
        browser = None
        await stopping.async_cancel()
        if not unloaded:
            browse()

    async def async_stop() -> None:
        nonlocal browser, unloaded
        unloaded = True
        if (stopping := browser) is not None:
            browser = None
            await stopping.async_cancel()

    browse()
    found_devices.browse_again = async_browse_again
    entry.async_on_unload(async_stop)
