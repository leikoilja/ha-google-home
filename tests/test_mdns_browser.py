"""Tests for browsing for Google Cast devices with mDNS, and reading their announcements."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Protocol
from unittest.mock import Mock, patch

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
    """A Cast device browser on a zeroconf instance whose cache this test fills."""

    cache: DNSCache = field(default_factory=DNSCache)
    client: Mock = field(default_factory=Mock)
    entry: Mock = field(default_factory=Mock)
    on_change: OnChange | None = None
    browser: Mock = field(default_factory=Mock)

    def cache_service(self, info: AsyncServiceInfo) -> None:
        """Put a device's mDNS records in the cache, as if it had answered."""
        self.cache.async_add_records(
            [info.dns_service(), info.dns_text(), *info.dns_addresses()]
        )

    def start(self, *cached: str) -> None:
        """Start browsing; the browser reports the cached service names as it starts."""
        zeroconf_instance = Mock(cache=self.cache)

        def browser(zc: object, types: list[str], handlers: list[OnChange]) -> Mock:
            assert (zc, types) == (zeroconf_instance, [CAST_SERVICE_TYPE])
            [self.on_change] = handlers
            for name in cached:
                self.change(name, ServiceStateChange.Added)
            return self.browser

        with patch(
            "custom_components.google_home.mdns.AsyncServiceBrowser",
            side_effect=browser,
        ):
            async_browse_cast_devices(
                Mock(), self.entry, zeroconf_instance, self.client
            )

    def change(self, name: str, state_change: ServiceStateChange) -> None:
        """Report a change to a service, as the browser does."""
        assert self.on_change is not None
        self.on_change(
            zeroconf=Mock(cache=self.cache),
            service_type=CAST_SERVICE_TYPE,
            name=name,
            state_change=state_change,
        )


KITCHEN = service("10.0.0.2", cd=b"ABCD", fn=b"Kitchen", md=b"Nest Audio")


def test_browse_reports_cached_device_at_once() -> None:
    """Report a device in the cache while the browser starts, before setup fetches the list.

    The browser is cancelled when the entry unloads.
    """
    browsing = Browsing()
    browsing.cache_service(KITCHEN)
    browsing.start(SERVICE_NAME)
    browsing.client.async_device_found.assert_called_once_with(
        "abcd", "Kitchen", "10.0.0.2"
    )
    browsing.entry.async_on_unload.assert_called_once_with(
        browsing.browser.async_cancel
    )


@pytest.mark.parametrize("cancelled", [False, True])
def test_browse_looks_up_device_not_cached(cancelled: bool) -> None:
    """Look up a device that isn't cached, and report it when it answers, unless the entry unloaded."""
    browsing = Browsing()
    lookups: list[asyncio.Future[None]] = []
    browsing.entry.async_create_background_task = Mock(
        side_effect=lambda _hass, target, _name: lookups.append(target)
    )

    async def answer(info: AsyncServiceInfo, zc: Mock, _timeout: float) -> bool:
        browsing.cache_service(KITCHEN)
        return info.load_from_cache(zc)

    async def run() -> None:
        browsing.start()
        browsing.change(SERVICE_NAME, ServiceStateChange.Added)
        browsing.client.async_device_found.assert_not_called()
        assert len(lookups) == 1
        task = asyncio.ensure_future(lookups[0])
        if cancelled:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    with patch.object(AsyncServiceInfo, "async_request", answer):
        asyncio.run(run())
    if cancelled:
        browsing.client.async_device_found.assert_not_called()
    else:
        browsing.client.async_device_found.assert_called_once_with(
            "abcd", "Kitchen", "10.0.0.2"
        )


def test_browse_ignores_removed_and_invalid_names() -> None:
    """Keep the address of a device that goes away, and skip names that aren't valid.

    Later changes are still reported.
    """
    browsing = Browsing()
    browsing.cache_service(KITCHEN)
    browsing.start()
    browsing.change(SERVICE_NAME, ServiceStateChange.Removed)
    # Longer than a DNS label can be
    browsing.change(f"{'a' * 70}.{CAST_SERVICE_TYPE}", ServiceStateChange.Added)
    browsing.client.async_device_found.assert_not_called()
    browsing.change(SERVICE_NAME, ServiceStateChange.Updated)
    browsing.client.async_device_found.assert_called_once_with(
        "abcd", "Kitchen", "10.0.0.2"
    )


def test_setup_browses_before_first_fetch() -> None:
    """Start browsing before setup fetches the list, and stop it even if setup fails.

    Found devices are fetched for with an update that waits for a running one.
    """
    events: list[str] = []
    browsed: list[FoundDevices] = []
    entry = Mock(
        data={"master_token": MASTER_TOKEN, "username": "", "password": ""},
        options={},
        async_on_unload=Mock(
            side_effect=lambda func: events.append(f"on unload: {func.__name__}")
        ),
    )
    coordinator = Mock()

    async def first_refresh() -> None:
        events.append("first refresh")
        raise ConfigEntryNotReady

    def browse(
        _hass: object, _entry: object, _zc: object, found_devices: FoundDevices
    ) -> None:
        events.append("browse")
        browsed.append(found_devices)

    coordinator.async_config_entry_first_refresh = first_refresh
    with (
        patch("custom_components.google_home.zeroconf.async_get_instance"),
        patch("custom_components.google_home.async_get_clientsession"),
        patch(
            "custom_components.google_home.DataUpdateCoordinator",
            return_value=coordinator,
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
    assert browsed[0].request_update is coordinator.async_refresh
