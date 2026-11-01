"""Tests for browsing for Google Cast devices with mDNS, and reading their announcements."""

import asyncio
from collections.abc import Coroutine, Iterator
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, field
from typing import Protocol, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from zeroconf import ServiceStateChange

# A compiled module, which pylint can't read
from zeroconf._cache import DNSCache  # pylint: disable=no-name-in-module
from zeroconf.asyncio import AsyncServiceInfo

from custom_components.google_home import async_setup_entry
from custom_components.google_home.const import CAST_SERVICE_TYPE
from custom_components.google_home.mdns import (
    FoundDevices,
    async_browse_cast_devices,
    cast_device_found,
    txt_value,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.exceptions import ConfigEntryNotReady

from .test_missing_devices import MASTER_TOKEN

SERVICE_NAME = f"Nest-Audio-0123.{CAST_SERVICE_TYPE}"


def service(*addresses: str, **properties: bytes) -> AsyncServiceInfo:
    """Return a Cast device's mDNS service, with its TXT properties."""
    return AsyncServiceInfo(
        CAST_SERVICE_TYPE,
        SERVICE_NAME,
        port=8009,
        properties={key.encode(): value for key, value in properties.items()},
        server="nest-audio-0123.local.",
        parsed_addresses=list(addresses),
    )


def cast_service(cloud_device_id: str, *addresses: str) -> AsyncServiceInfo:
    """Return the mDNS service of a speaker named after Google's other ID for it."""
    return AsyncServiceInfo(
        CAST_SERVICE_TYPE,
        f"{cloud_device_id}.{CAST_SERVICE_TYPE}",
        port=8009,
        properties={
            b"cd": cloud_device_id.encode(),
            b"fn": cloud_device_id.encode(),
            b"md": b"Nest Audio",
        },
        server=f"{cloud_device_id}.local.",
        parsed_addresses=list(addresses),
    )


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        pytest.param(
            service("10.0.0.2", cd=b"ABCD", fn=b"Kitchen", md=b"Nest Audio"),
            ("abcd", "Kitchen", "10.0.0.2"),
            id="ipv4",
        ),
        pytest.param(
            service("fe80::1", "2001:db8::2", "10.0.0.2", cd=b"ABCD", fn=b"Kitchen"),
            ("abcd", "Kitchen", "10.0.0.2"),
            id="ipv4-first",
        ),
        pytest.param(
            service("fe80::1", "2001:db8::2", cd=b"ABCD", fn=b"Kitchen"),
            ("abcd", "Kitchen", "2001:db8::2"),
            id="ipv6-not-link-local",
        ),
        pytest.param(
            service("10.0.0.2", cd=b"ABCD"),
            ("abcd", SERVICE_NAME, "10.0.0.2"),
            id="no-friendly-name",
        ),
        pytest.param(service("fe80::1", cd=b"ABCD"), None, id="link-local-only"),
        pytest.param(service(cd=b"ABCD"), None, id="no-address"),
        pytest.param(service("10.0.0.2", fn=b"Kitchen"), None, id="no-id"),
        pytest.param(service("10.0.0.2", cd=b"\xff\xfe"), None, id="invalid-id"),
        pytest.param(
            service("10.0.0.2", cd=b"ABCD", md=b"Google Cast Group"),
            None,
            id="cast-group",
        ),
    ],
)
def test_cast_device_found(
    info: AsyncServiceInfo, expected: tuple[str, str, str] | None
) -> None:
    """Report Google's ID, name and a usable address of a Cast device, but not of a group."""
    assert cast_device_found(info) == expected


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        pytest.param({b"fn": b"Kitchen"}, "Kitchen", id="bytes"),
        # zeroconf stores it as bytes, which decode as UTF-8
        pytest.param({"fn": "K\u00fcche"}, "K\u00fcche", id="str"),
        pytest.param({b"md": b"Nest Audio"}, None, id="missing"),
        pytest.param({b"fn": None}, None, id="no-value"),
        pytest.param({b"fn": b"\xff\xfe"}, None, id="not-utf-8"),
    ],
)
def test_txt_value(
    properties: dict[str | bytes, str | bytes | None], expected: str | None
) -> None:
    """Decode a value of a Cast device's TXT record as glocaltokens 1.2.0's scanner did."""
    info = AsyncServiceInfo(
        CAST_SERVICE_TYPE, SERVICE_NAME, port=8009, properties=properties
    )
    assert txt_value(info, "fn") == expected


class OnChange(Protocol):
    """A handler of an mDNS service browser."""

    def __call__(
        self,
        *,
        zeroconf: object,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle a change to a service."""


@dataclass
class Browsing:
    """Cast device browsers on a zeroconf instance whose cache this test fills.

    As zeroconf's does, each browser reports every service whose PTR record is cached
    as added when it starts, before it returns. The test reports later changes, which
    the latest browser gets. Lookups of services that aren't cached are kept to run.
    """

    found_devices: Mock | FoundDevices = field(default_factory=Mock)
    cache: DNSCache = field(default_factory=DNSCache)
    entry: Mock = field(default_factory=Mock)
    # The services whose PTR record is cached, in the order they arrived
    ptrs: list[str] = field(default_factory=list)
    browsers: list[Mock] = field(default_factory=list)
    lookups: list[Coroutine[object, object, None]] = field(default_factory=list)
    on_change: OnChange | None = None

    def __post_init__(self) -> None:
        """Keep the lookups that the browser starts, instead of running them."""
        self.zeroconf = Mock(cache=self.cache)
        self.entry.async_create_background_task = Mock(
            side_effect=lambda _hass, target, _name: self.lookups.append(target)
        )

    def cache_service(self, info: AsyncServiceInfo, *, ptr: bool = True) -> None:
        """Put a device's mDNS records in the cache, as if it had answered.

        With ptr, also its PTR record, so browsers that start report it.
        """
        self.cache.async_add_records(
            [info.dns_service(), info.dns_text(), *info.dns_addresses()]
        )
        if ptr and info.name not in self.ptrs:
            self.ptrs.append(info.name)

    def new_browser(
        self, zc: object, types: list[str], handlers: list[OnChange]
    ) -> Mock:
        """Start a browser, which reports the cached PTR records as added."""
        assert (zc, types) == (self.zeroconf, [CAST_SERVICE_TYPE])
        [self.on_change] = handlers
        for name in self.ptrs:
            self.change(name, ServiceStateChange.Added)
        browser = Mock(async_cancel=AsyncMock())
        self.browsers.append(browser)
        return browser

    @property
    def reported(self) -> Mock:
        """Return the fake found devices' record of what the browsers reported."""
        return cast(Mock, cast(Mock, self.found_devices).async_device_found)

    def patched(self) -> AbstractContextManager[Mock]:
        """Make the entry browse with this test's browsers."""
        return patch(
            "custom_components.google_home.mdns.AsyncServiceBrowser",
            side_effect=self.new_browser,
        )

    def start(self) -> None:
        """Start browsing for the entry."""
        async_browse_cast_devices(Mock(), self.entry, self.zeroconf, self.found_devices)

    def change(self, name: str, state_change: ServiceStateChange) -> None:
        """Report a change to a service, as the browser does."""
        assert self.on_change is not None
        self.on_change(
            zeroconf=Mock(cache=self.cache),
            service_type=CAST_SERVICE_TYPE,
            name=name,
            state_change=state_change,
        )

    def expire(self, name: str) -> None:
        """Let a service's records expire, which the browser reports as removed."""
        self.ptrs.remove(name)
        self.cache = self.zeroconf.cache = DNSCache()
        self.change(name, ServiceStateChange.Removed)

    async def browse_again(self) -> None:
        """Browse again, as a fetch of Google's list that worked does."""
        assert self.found_devices.browse_again is not None
        await self.found_devices.browse_again()

    async def unload(self) -> None:
        """Run what the entry runs as it unloads."""
        [(stop,)] = [c.args for c in self.entry.async_on_unload.call_args_list]
        await stop()


@pytest.fixture(name="browsing")
def fixture_browsing() -> Iterator[Browsing]:
    """Browse with fake browsers on a cache that the test fills."""
    browsing = Browsing()
    with browsing.patched():
        yield browsing


KITCHEN = service("10.0.0.2", cd=b"ABCD", fn=b"Kitchen", md=b"Nest Audio")


def reports(browsing: Browsing) -> list[tuple[str, bool]]:
    """Return each address that the browsers reported, and whether it was replayed."""
    return [(c.args[2], c.kwargs["replayed"]) for c in browsing.reported.call_args_list]


def test_browse_reports_cached_device_at_once(browsing: Browsing) -> None:
    """Report a device in the cache while the browser starts, before setup fetches the list.

    It's news: nothing reported it before. The browser is cancelled when the entry
    unloads.
    """
    browsing.cache_service(KITCHEN)
    browsing.start()
    browsing.reported.assert_called_once_with(
        "abcd", "Kitchen", "10.0.0.2", replayed=False
    )
    [browser] = browsing.browsers
    asyncio.run(browsing.unload())
    browser.async_cancel.assert_awaited_once()


@pytest.mark.parametrize("cancelled", [False, True])
def test_browse_looks_up_device_not_cached(browsing: Browsing, cancelled: bool) -> None:
    """Look up a device that isn't cached, and report it when it answers, unless the entry unloaded."""

    async def answer(info: AsyncServiceInfo, zc: Mock, _timeout: float) -> bool:
        browsing.cache_service(KITCHEN)
        return info.load_from_cache(zc)

    async def run() -> None:
        browsing.start()
        browsing.change(SERVICE_NAME, ServiceStateChange.Added)
        browsing.reported.assert_not_called()
        assert len(browsing.lookups) == 1
        task = asyncio.ensure_future(browsing.lookups[0])
        if cancelled:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    with patch.object(AsyncServiceInfo, "async_request", answer):
        asyncio.run(run())
    if cancelled:
        browsing.reported.assert_not_called()
    else:
        browsing.reported.assert_called_once_with(
            "abcd", "Kitchen", "10.0.0.2", replayed=False
        )


def test_browse_ignores_removed_and_invalid_names(browsing: Browsing) -> None:
    """Keep the address of a device that goes away, and skip names that aren't valid.

    Later changes are still reported.
    """
    browsing.cache_service(KITCHEN, ptr=False)
    browsing.start()
    browsing.change(SERVICE_NAME, ServiceStateChange.Removed)
    # Longer than a DNS label can be
    browsing.change(f"{'a' * 70}.{CAST_SERVICE_TYPE}", ServiceStateChange.Added)
    browsing.reported.assert_not_called()
    browsing.change(SERVICE_NAME, ServiceStateChange.Updated)
    browsing.reported.assert_called_once_with(
        "abcd", "Kitchen", "10.0.0.2", replayed=False
    )


def test_browse_again_replaces_browser(browsing: Browsing) -> None:
    """Cancel the browser, then start another, which replays the cache.

    Each browser is cancelled once: the old one when browsing again, the last one
    when the entry unloads. Nothing browses after that.
    """

    async def run() -> None:
        browsing.cache_service(KITCHEN)
        browsing.start()
        first = browsing.browsers[0]
        await browsing.browse_again()
        first.async_cancel.assert_awaited_once()
        [_, second] = browsing.browsers
        second.async_cancel.assert_not_awaited()
        await browsing.unload()
        await browsing.browse_again()
        second.async_cancel.assert_awaited_once()

    asyncio.run(run())
    assert len(browsing.browsers) == 2
    assert reports(browsing) == [("10.0.0.2", False), ("10.0.0.2", True)]


def test_unload_while_browser_is_replaced(browsing: Browsing) -> None:
    """Start no browser when the entry unloads while the old one is cancelled.

    Nor cancel the old one twice, which zeroconf doesn't allow.
    """

    async def run() -> None:
        browsing.start()
        [first] = browsing.browsers
        cancelling = asyncio.Event()
        cancelled = asyncio.Event()

        async def cancel() -> None:
            cancelling.set()
            await cancelled.wait()

        first.async_cancel.side_effect = cancel
        replacing = asyncio.ensure_future(browsing.browse_again())
        await cancelling.wait()
        # Cancelling the old browser again would wait for that first cancel
        async with asyncio.timeout(1):
            await browsing.unload()
        cancelled.set()
        await replacing
        first.async_cancel.assert_awaited_once()

    asyncio.run(run())
    assert len(browsing.browsers) == 1


def test_browse_again_replays_only_cached_services(browsing: Browsing) -> None:
    """Count a service added again while its PTR record is cached as replayed, and others as news.

    The device's PTR record expires and it comes back: that's news, and so is the
    browser's report of it while browsing again. An update isn't a replay, even of
    a cached service.
    """

    async def run() -> None:
        browsing.cache_service(KITCHEN)
        browsing.start()
        await browsing.browse_again()
        browsing.change(SERVICE_NAME, ServiceStateChange.Updated)
        browsing.expire(SERVICE_NAME)
        browsing.cache_service(KITCHEN)
        browsing.change(SERVICE_NAME, ServiceStateChange.Added)
        await browsing.browse_again()

    asyncio.run(run())
    assert reports(browsing) == [
        ("10.0.0.2", False),
        ("10.0.0.2", True),
        ("10.0.0.2", False),
        ("10.0.0.2", False),
        ("10.0.0.2", True),
    ]


def test_update_before_ptr_record_doesnt_make_it_a_replay(browsing: Browsing) -> None:
    """Count a device's first PTR record as news after its TXT record came alone.

    zeroconf reports a new TXT record as an update, even before the PTR record
    arrives. Looking the device up then finds no address, so nothing is reported. When
    the PTR record comes, with the other records, the browser reports only that the
    device was added.
    """
    txt_only = service(cd=b"ABCD", fn=b"Kitchen", md=b"Nest Audio")

    async def time_out(_info: AsyncServiceInfo, _zc: Mock, _timeout: float) -> bool:
        return False

    async def run() -> None:
        browsing.start()
        browsing.cache.async_add_records([txt_only.dns_text()])
        browsing.change(SERVICE_NAME, ServiceStateChange.Updated)
        [lookup] = browsing.lookups
        with patch.object(AsyncServiceInfo, "async_request", time_out):
            await lookup
        browsing.reported.assert_not_called()
        browsing.cache_service(KITCHEN)
        browsing.change(SERVICE_NAME, ServiceStateChange.Added)

    asyncio.run(run())
    assert reports(browsing) == [("10.0.0.2", False)]


def test_replayed_lookup_stays_replayed(browsing: Browsing) -> None:
    """Report a cached service that needs a lookup as replayed when the lookup ends.

    Its PTR record is cached but not the others, so browsing again looks it up, and
    the lookup ends after other work.
    """

    async def answer(info: AsyncServiceInfo, zc: Mock, _timeout: float) -> bool:
        browsing.cache_service(KITCHEN)
        return info.load_from_cache(zc)

    async def run() -> None:
        browsing.cache_service(KITCHEN)
        browsing.start()
        browsing.cache = browsing.zeroconf.cache = DNSCache()
        await browsing.browse_again()
        [lookup] = browsing.lookups
        with patch.object(AsyncServiceInfo, "async_request", answer):
            await lookup

    asyncio.run(run())
    assert reports(browsing) == [("10.0.0.2", False), ("10.0.0.2", True)]


def test_setup_browses_before_first_fetch() -> None:
    """Start browsing before setup fetches the list, and stop it even if setup fails.

    Found devices are fetched for with an update that waits for a running one.
    """
    events: list[str] = []
    browsed: list[FoundDevices] = []
    entry = Mock(
        data={"master_token": MASTER_TOKEN, "username": "", "password": ""},
        options={},
        pref_disable_polling=False,
        async_on_unload=Mock(
            side_effect=lambda func: events.append(f"on unload: {func.__name__}")
        ),
    )
    account = Mock()

    async def first_refresh() -> None:
        events.append("first refresh")
        raise ConfigEntryNotReady

    def browse(
        _hass: object, _entry: object, _zc: object, found_devices: FoundDevices
    ) -> None:
        events.append("browse")
        browsed.append(found_devices)

    account.async_config_entry_first_refresh = first_refresh
    with (
        patch("custom_components.google_home.zeroconf.async_get_instance"),
        patch("custom_components.google_home.async_get_clientsession"),
        # It needs Home Assistant's issue registry
        patch("custom_components.google_home.async_show_polling_disabled"),
        patch(
            "custom_components.google_home.GoogleAccountCoordinator",
            return_value=account,
        ),
        patch(
            "custom_components.google_home.async_browse_cast_devices",
            side_effect=browse,
        ),
        pytest.raises(ConfigEntryNotReady),
    ):
        asyncio.run(async_setup_entry(Mock(), entry))
    assert events == [
        "on unload: async_stop",
        "browse",
        "first refresh",
    ]
    assert len(browsed) == 1
    assert browsed[0].request_update is account.async_refresh
