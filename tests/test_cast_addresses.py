"""Tests for how mDNS gives devices their addresses around fetches of Google's list.

glocaltokens fetches the list without its own scan. After each fetch that works,
the integration's browser starts again: it replays mDNS's cache and asks the
network. Times are seconds since setup fetched the list.
"""

import asyncio
from http import HTTPStatus
from typing import cast
from unittest.mock import MagicMock, Mock, patch

from glocaltokens.client import Device
import pytest
from zeroconf import ServiceStateChange, current_time_millis

# Compiled modules, which pylint can't read
from zeroconf._cache import DNSCache  # pylint: disable=no-name-in-module
from zeroconf._dns import DNSAddress  # pylint: disable=no-name-in-module
from zeroconf.asyncio import AsyncServiceInfo

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import CAST_SERVICE_TYPE
from custom_components.google_home.models import GoogleHomeDevice

from .conftest import Timer
from .test_found_devices import Network, settle
from .test_known_hosts import fake_session
from .test_mdns_browser import Browsing, cast_service
from .test_missing_devices import MASTER_TOKEN, answered, found, until


def test_fetch_asks_glocaltokens_without_discovery(
    clock: Mock, timers: list[Timer]
) -> None:
    """Fetch Google's list without glocaltokens' own mDNS scan, which the integration replaces."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    asyncio.run(network.setup())

    glocaltokens = cast(Mock, network.client._client)  # noqa: SLF001  # pylint: disable=protected-access
    glocaltokens.get_google_devices.assert_called_once_with(
        disable_discovery=True, force_homegraph_reload=True
    )


def service_name(cloud_device_id: str) -> str:
    """Return the mDNS name of a speaker named after Google's other ID for it."""
    return f"{cloud_device_id}.{CAST_SERVICE_TYPE}"


@pytest.mark.parametrize("polling", [True, False])
def test_device_back_at_new_address_found_after_fetch(
    clock: Mock, timers: list[Timer], polling: bool
) -> None:
    """Find a listed device at its new address when the browser starts again after a fetch.

    Its records expired while it was offline, so it kept its old address, and Home
    Assistant didn't receive its announcement when it came back. It answers the new
    browser's queries, so its next update asks it at the new address, without
    another fetch. With polling off, which stops the fetches for found devices, the
    updates are those that the user asks for, and the fetch at one of them browses
    again too.
    """
    network = Network(clock, timers, [found("kitchen", None)])
    browsing = Browsing(found_devices=network.client.found_devices)
    if not polling:
        network.client.found_devices.async_stop()

    async def run() -> None:
        browsing.cache_service(cast_service("kitchen", "10.0.0.2"))
        browsing.start()
        await network.setup()
        await network.update(15)
        browsing.expire(service_name("kitchen"))
        await network.update(600)
        browsers = len(browsing.browsers)
        await network.update(1200)
        # Only a browser that starts asks the network for every Cast device
        assert len(browsing.browsers) == browsers + 1
        browsing.cache_service(cast_service("kitchen", "10.0.0.9"))
        browsing.change(service_name("kitchen"), ServiceStateChange.Added)
        await network.update(1215)

    with browsing.patched():
        asyncio.run(run())
    assert network.fetches == [0, 1200]
    assert network.polled == [
        ("kitchen", "10.0.0.2"),
        ("kitchen", "10.0.0.2"),
        ("kitchen", "10.0.0.2"),
        ("kitchen", "10.0.0.9"),
    ]


def test_failed_fetch_doesnt_browse_again(clock: Mock, timers: list[Timer]) -> None:
    """Browse again only after a fetch that got Google's list."""
    network = Network(clock, timers, [found("kitchen", None)])
    browsing = Browsing(found_devices=network.client.found_devices)

    async def run() -> None:
        browsing.start()
        await network.setup()
        network.error = answered(HTTPStatus.SERVICE_UNAVAILABLE)
        await network.update(1200)

    with browsing.patched():
        asyncio.run(run())
    assert network.fetches == [0, 1200]
    assert len(browsing.browsers) == 2


def test_removed_cached_device_replayed_without_fetch(
    clock: Mock, timers: list[Timer]
) -> None:
    """Don't fetch for a device that Google removed when the browser replays it from the cache.

    It stays in mDNS's cache, so each browser that starts reports it again, also once
    its other records have expired and a lookup reports it after the fetch. A device
    that announces itself for the first time still makes the list be fetched.
    """
    network = Network(clock, timers, [found("kitchen", None), found("office", None)])
    browsing = Browsing(found_devices=network.client.found_devices)

    async def answer(info: AsyncServiceInfo, zc: Mock, _timeout: float) -> bool:
        browsing.cache_service(cast_service("office", "10.0.0.3"))
        return info.load_from_cache(zc)

    async def run() -> None:
        browsing.cache_service(cast_service("kitchen", "10.0.0.2"))
        browsing.cache_service(cast_service("office", "10.0.0.3"))
        browsing.start()
        await network.setup()
        network.listed = [found("kitchen", None)]
        await network.update(1200)
        assert network.live() == []
        await network.update(2400)
        assert network.live() == []
        # Only the office's PTR record is still cached
        browsing.cache = browsing.zeroconf.cache = DNSCache()
        browsing.cache_service(cast_service("kitchen", "10.0.0.2"))
        lookups = len(browsing.lookups)
        await network.update(3600)
        [lookup] = browsing.lookups[lookups:]
        with patch.object(AsyncServiceInfo, "async_request", answer):
            await lookup
        assert network.live() == []
        clock.return_value = 3700
        browsing.cache_service(cast_service("tv", "10.0.0.7"))
        browsing.change(service_name("tv"), ServiceStateChange.Added)
        assert network.live() == [3730]

    with browsing.patched():
        asyncio.run(run())
    assert network.fetches == [0, 1200, 2400, 3600]


def test_cached_name_in_other_case_is_the_same(
    clock: Mock, timers: list[Timer]
) -> None:
    """Take a service's name in any case for the one whose PTR record is cached.

    Google removed the office speaker, which stays cached. Its PTR record comes again
    with its name in another case, which zeroconf keeps without reporting it as
    added, so the next browser replays that spelling: no fetch. When the record
    expires under it and the speaker comes back under its first spelling, that's
    news, so the list is fetched 30 seconds later.
    """
    network = Network(clock, timers, [found("kitchen", None), found("office", None)])
    browsing = Browsing(found_devices=network.client.found_devices)
    office = service_name("office")
    renamed = office.replace("office", "Office", 1)

    async def run() -> None:
        browsing.cache_service(cast_service("kitchen", "10.0.0.2"))
        browsing.cache_service(cast_service("office", "10.0.0.3"))
        browsing.start()
        await network.setup()
        network.listed = [found("kitchen", None)]
        await network.update(1200)
        browsing.ptrs[browsing.ptrs.index(office)] = renamed
        await network.update(2400)
        assert network.live() == []
        browsing.ptrs.remove(renamed)
        browsing.change(renamed, ServiceStateChange.Removed)
        clock.return_value = 2500
        browsing.ptrs.append(office)
        browsing.change(office, ServiceStateChange.Added)
        assert network.live() == [2530]

    with browsing.patched():
        asyncio.run(run())
    assert network.fetches == [0, 1200, 2400]


def test_late_lookup_keeps_newer_address(clock: Mock, timers: list[Timer]) -> None:
    """Keep the address that a newer report gave, when a replayed lookup ends late.

    Browsing again after a fetch replays the speaker, whose TXT record isn't cached,
    so it's looked up. Meanwhile its IPv4 address expires, though its record stays
    cached until zeroconf cleans up, and it announces an IPv6 one. zeroconf's lookup
    ignores records that expire, so it ends with both addresses, and IPv4 comes
    first. The speaker keeps the one that the cache still has unexpired.
    """
    network = Network(clock, timers, [found("kitchen", None)])
    browsing = Browsing(found_devices=network.client.found_devices)
    kitchen = cast_service("kitchen", "10.0.0.2")
    both = cast_service("kitchen", "10.0.0.2", "2001:db8::2")

    async def with_both(info: AsyncServiceInfo, _zc: Mock, _timeout: float) -> bool:
        return info.load_from_cache(Mock(cache=cache_of(both)))

    async def run() -> None:
        browsing.cache_service(kitchen)
        browsing.start()
        await network.setup()
        browsing.cache = browsing.zeroconf.cache = DNSCache()
        browsing.cache.async_add_records(
            [kitchen.dns_service(), *kitchen.dns_addresses()]
        )
        await network.update(1200)
        [lookup] = browsing.lookups
        [ipv4] = kitchen.dns_addresses()
        expired = current_time_millis() - (ipv4.ttl + 1) * 1000
        browsing.cache.async_add_records(
            [
                DNSAddress(
                    ipv4.name,
                    ipv4.type,
                    ipv4.class_,
                    ipv4.ttl,
                    ipv4.address,
                    created=expired,
                )
            ]
        )
        browsing.cache_service(cast_service("kitchen", "2001:db8::2"))
        browsing.change(service_name("kitchen"), ServiceStateChange.Updated)
        with patch.object(AsyncServiceInfo, "async_request", with_both):
            await lookup
        await network.update(1215)

    with browsing.patched():
        asyncio.run(run())
    assert network.fetches == [0, 1200]
    assert network.polled[-1] == ("kitchen", "2001:db8::2")


def cache_of(info: AsyncServiceInfo) -> DNSCache:
    """Return a cache with a service's records."""
    cache = DNSCache()
    cache.async_add_records(
        [info.dns_service(), info.dns_text(), *info.dns_addresses()]
    )
    return cache


def test_device_updated_before_announced_fetched_for(
    clock: Mock, timers: list[Timer]
) -> None:
    """Fetch for a new device whose TXT record came before its PTR record.

    zeroconf reports the TXT record as an update, whose lookup finds no address. The
    PTR record that comes later is news, so the list is fetched 30 seconds after it.
    """
    network = Network(clock, timers, [found("kitchen", None)])
    browsing = Browsing(found_devices=network.client.found_devices)

    async def time_out(_info: AsyncServiceInfo, _zc: Mock, _timeout: float) -> bool:
        return False

    async def run() -> None:
        browsing.start()
        await network.setup()
        clock.return_value = 100
        browsing.cache.async_add_records([cast_service("tv").dns_text()])
        browsing.change(service_name("tv"), ServiceStateChange.Updated)
        [lookup] = browsing.lookups
        with patch.object(AsyncServiceInfo, "async_request", time_out):
            await lookup
        assert network.live() == []
        clock.return_value = 110
        browsing.cache_service(cast_service("tv", "10.0.0.7"))
        browsing.change(service_name("tv"), ServiceStateChange.Added)

    with browsing.patched():
        asyncio.run(run())
    assert network.live() == [140]


async def set_up(network: Network) -> None:
    """Run setup's first update, which waits a while for mDNS to give addresses."""
    network.client.setting_up = True
    try:
        await network.update(0)
    finally:
        network.client.setting_up = False


def test_setup_waits_for_mdns_addresses(clock: Mock, timers: list[Timer]) -> None:
    """Ask the devices that mDNS finds just after Google's list arrives at those addresses at setup.

    Setup waits until every device in the list has an address, however many other
    Cast devices mDNS finds meanwhile. The known hosts aren't asked.
    """
    session = MagicMock()
    network = Network(
        clock,
        timers,
        [found("kitchen", None), found("office", None)],
        session,
        ["10.0.1.9"],
    )
    browsing = Browsing(found_devices=network.client.found_devices)

    async def answer(cloud_device_id: str, address: str) -> None:
        browsing.cache_service(cast_service(cloud_device_id, address))
        browsing.change(service_name(cloud_device_id), ServiceStateChange.Added)
        await settle()

    async def run() -> None:
        browsing.start()
        setup = asyncio.ensure_future(set_up(network))
        # The fetch has browsed again, so setup waits
        await until(lambda: len(browsing.browsers) == 2)
        await settle()
        assert not setup.done()
        await answer("kitchen", "10.0.0.2")
        await answer("tv", "10.0.0.7")
        assert not setup.done()
        await answer("office", "10.0.0.3")
        async with asyncio.timeout(1):
            await setup

    with (
        browsing.patched(),
        patch("custom_components.google_home.mdns.CAST_SETUP_WAIT", 30),
    ):
        asyncio.run(run())
    assert network.polled == [("kitchen", "10.0.0.2"), ("office", "10.0.0.3")]
    session.get.assert_not_called()


def test_setup_waits_at_most_a_while(clock: Mock, timers: list[Timer]) -> None:
    """Ask the known hosts once setup has waited long enough, and use mDNS's address later.

    The kitchen speaker answers mDNS only after that, so setup asks it at its known
    host. Its next update asks it at the address that mDNS gave, without a fetch.
    """
    network = Network(
        clock,
        timers,
        [found("kitchen", None, cloud_device_id="aaaa")],
        fake_session({"10.0.1.9": ("Kitchen", "aaaa")}),
        ["10.0.1.9"],
    )
    browsing = Browsing(found_devices=network.client.found_devices)

    async def run() -> None:
        browsing.start()
        async with asyncio.timeout(1):
            await set_up(network)
        browsing.cache_service(cast_service("aaaa", "10.0.0.2"))
        browsing.change(service_name("aaaa"), ServiceStateChange.Added)
        await network.update(15)

    with (
        browsing.patched(),
        patch("custom_components.google_home.mdns.CAST_SETUP_WAIT", 0.01),
    ):
        asyncio.run(run())
    assert network.fetches == [0]
    assert network.polled == [("kitchen", "10.0.1.9"), ("kitchen", "10.0.0.2")]


@pytest.mark.parametrize(
    ("device", "setting_up"),
    [
        pytest.param(found("kitchen", "10.0.0.2"), True, id="cached"),
        pytest.param(found("hall", None), True, id="no-cloud-id"),
        pytest.param(found("bedroom", None), True, id="excluded-home"),
        pytest.param(found("kitchen", None), False, id="after-setup"),
    ],
)
def test_no_wait_for_mdns(
    clock: Mock, timers: list[Timer], device: Device, setting_up: bool
) -> None:
    """Don't wait for mDNS when every device has an address or can't get one, or after setup.

    A device without Google's other ID for it can't be matched, and a device of an
    excluded home isn't added.
    """
    if device.device_id == "hall":
        device.cloud_device_id = None
    if device.device_id == "bedroom":
        device.home_id = "holiday-house"
    network = Network(clock, timers, [device], excluded_homes=["holiday-house"])

    async def run() -> None:
        network.client.setting_up = setting_up
        async with asyncio.timeout(1):
            await network.update(0)

    with patch("custom_components.google_home.mdns.CAST_SETUP_WAIT", 30):
        asyncio.run(run())
    assert network.fetches == [0]


def test_known_host_doesnt_replace_address_mdns_finds_meanwhile() -> None:
    """Keep the address that mDNS reports while the known hosts are asked."""
    client: GlocaltokensApiClient | None = None
    session = fake_session({"10.0.1.9": ("Kitchen", "aaaa")})
    get = session.get

    def get_after_mdns(url: str, **kwargs: object) -> MagicMock:
        assert client is not None
        client.found_devices.async_device_found("aaaa", "Kitchen", "10.0.0.2")
        return cast(MagicMock, get(url, **kwargs))

    session.get = Mock(side_effect=get_after_mdns)
    client = GlocaltokensApiClient(
        Mock(), session, master_token=MASTER_TOKEN, known_hosts=["10.0.1.9"]
    )
    kitchen = GoogleHomeDevice("kitchen", "Kitchen", "token", cloud_device_id="aaaa")
    client.google_devices = [kitchen]

    assert asyncio.run(client.async_use_known_hosts()) == {}
    assert kitchen.ip_address == "10.0.0.2"
