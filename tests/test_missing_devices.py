"""Tests for finding devices that didn't answer at setup."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, Mock

from glocaltokens.client import Device
from glocaltokens.scanner import NetworkDevice
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import FETCH_DEVICES_EVERY
from custom_components.google_home.entity import async_add_device_entities
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeTimersSensor,
)

# glocaltokens accepts only tokens of the real length
MASTER_TOKEN = "aas_et/" + "x" * 216
LOCAL_AUTH_TOKEN = "x" * 108


def found(device_id: str, ip_address: str | None) -> Device:
    """Return a device as glocaltokens returns it, with the address mDNS found."""
    network_device = (
        NetworkDevice(device_id, ip_address, 8009, "Nest Audio", device_id)
        if ip_address
        else None
    )
    return Device(
        device_id,
        device_id,
        LOCAL_AUTH_TOKEN,
        network_device,
        hardware="Nest Audio",
        cloud_device_id=device_id,
    )


def make_client(*ip_addresses: str | None) -> tuple[GlocaltokensApiClient, Mock]:
    """Return a client that fetched Google's list once, and its fake glocaltokens."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    client = GlocaltokensApiClient(hass, Mock(), master_token=MASTER_TOKEN)
    client.google_devices = [
        GoogleHomeDevice(f"device{index}", f"Device {index}", "token", ip_address)
        for index, ip_address in enumerate(ip_addresses)
    ]
    client.google_devices_fetched = True
    # Unless a test says otherwise, Google and mDNS return the same devices again
    glocaltokens = Mock(
        get_google_devices=Mock(
            return_value=[
                found(device.device_id, device.ip_address)
                for device in client.google_devices
            ]
        ),
        homegraph=Mock(),
    )
    client._client = glocaltokens  # noqa: SLF001  # pylint: disable=protected-access
    return client, glocaltokens


def fetches_in(client: GlocaltokensApiClient, glocaltokens: Mock, updates: int) -> int:
    """Return how often Google's list was fetched again after this many more updates."""

    client.collect_data_from_endpoints = AsyncMock()  # type: ignore[method-assign]

    async def run() -> None:
        for _ in range(updates):
            await client.update_google_devices_information()

    asyncio.run(run())
    return int(glocaltokens.get_google_devices.call_count)


def test_no_fetch_when_every_device_has_an_address() -> None:
    """Don't ask Google again while every device has an address."""
    client, glocaltokens = make_client("10.0.0.2", "10.0.0.3")

    assert fetches_in(client, glocaltokens, FETCH_DEVICES_EVERY * 3) == 0


def test_fetch_every_few_updates_while_a_device_has_no_address() -> None:
    """Ask Google again every few updates, not on every one, while a device is missing."""
    client, glocaltokens = make_client("10.0.0.2", None)

    assert fetches_in(client, glocaltokens, FETCH_DEVICES_EVERY - 1) == 0
    assert fetches_in(client, glocaltokens, 1) == 1
    assert fetches_in(client, glocaltokens, FETCH_DEVICES_EVERY) == 2


def fetch(client: GlocaltokensApiClient) -> None:
    """Run the update on which Google's list is fetched again."""
    client.updates_until_fetch = 1
    asyncio.run(client.async_find_missing_devices())


def test_keep_address_mdns_missed() -> None:
    """Keep the address of a device that mDNS found before but missed this time."""
    client, glocaltokens = make_client("10.0.0.2", None)
    glocaltokens.get_google_devices.return_value = [
        found("device0", None),
        found("device1", "10.0.0.3"),
    ]

    fetch(client)

    assert [device.ip_address for device in client.google_devices] == [
        "10.0.0.2",
        "10.0.0.3",
    ]


@pytest.mark.parametrize("homegraph_fails", [True, False])
def test_keep_devices_when_fetch_fails(homegraph_fails: bool) -> None:
    """Keep the devices of the last fetch when Google can't be reached."""
    client, glocaltokens = make_client("10.0.0.2", None)
    devices = list(client.google_devices)
    if homegraph_fails:
        glocaltokens.homegraph = None
    else:
        glocaltokens.get_google_devices.side_effect = RequestsConnectionError

    fetch(client)

    assert client.google_devices == devices
    assert client.google_devices_fetched


def add_entities(
    coordinator: Mock, *entity_classes: type, needs_answer: bool = True
) -> tuple[Callable[[], None], Callable[[], list[tuple[str, str]]]]:
    """Add entities as a platform does, and return the update listener and a reader.

    The reader returns the entities added since it was last called, by device and label.
    """
    async_add_entities = Mock()
    async_add_device_entities(
        Mock(),
        coordinator,
        Mock(),
        async_add_entities,
        *entity_classes,
        needs_answer=needs_answer,
    )
    [listener] = coordinator.async_add_listener.call_args.args

    def added() -> list[tuple[str, str]]:
        entities = [
            (entity.device_id, entity.label)
            for call in async_add_entities.call_args_list
            for entity in call.args[0]
        ]
        async_add_entities.reset_mock()
        return entities

    return listener, added


def test_add_entities_once_device_answers() -> None:
    """Add a device's entities when it first answers, at setup or later, and only once."""
    kitchen = GoogleHomeDevice("kitchen", "Kitchen", "token", "10.0.0.2")
    bedroom = GoogleHomeDevice("bedroom", "Bedroom", "token")
    bedroom.available = False
    coordinator = Mock(data=[kitchen, bedroom])

    listener, added = add_entities(
        coordinator, GoogleHomeAlarmsSensor, GoogleHomeTimersSensor
    )

    assert added() == [("kitchen", "alarms"), ("kitchen", "timers")]
    listener()
    assert added() == []
    # The bedroom speaker was offline at setup and answers now
    bedroom.ip_address = "10.0.0.3"
    bedroom.available = True
    listener()
    assert added() == [("bedroom", "alarms"), ("bedroom", "timers")]
    listener()
    assert added() == []


def test_add_device_sensor_for_device_found_later() -> None:
    """Add a device sensor for a device that a later fetch finds, answering or not."""
    kitchen = GoogleHomeDevice("kitchen", "Kitchen", "token")
    kitchen.available = False
    # Setup couldn't reach Google, so it found no devices
    coordinator = Mock(data=[])

    listener, added = add_entities(
        coordinator, GoogleHomeDeviceSensor, needs_answer=False
    )

    assert added() == []
    coordinator.data = [kitchen]
    listener()
    assert added() == [("kitchen", "device")]
    listener()
    assert added() == []
