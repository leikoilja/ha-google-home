"""Tests for fetching Google's device list again after setup."""

import asyncio
from collections.abc import Callable, Iterator
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from glocaltokens.client import Device
from glocaltokens.scanner import NetworkDevice
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.google_home import async_remove_config_entry_device
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    FETCH_DEVICES_EVERY,
    FETCH_DEVICES_INTERVAL,
)
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
ALARM_ID = "alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51"
TIMER_ID = "timer/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51"
HOUR = 60 * 60


@pytest.fixture(name="clock")
def fixture_clock() -> Iterator[Mock]:
    """Set the time the client reads, in seconds since setup fetched Google's list."""
    with patch(
        "custom_components.google_home.api.monotonic", return_value=0.0
    ) as monotonic:
        yield monotonic


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


def make_client(
    *ip_addresses: str | None, session: Mock | None = None
) -> tuple[GlocaltokensApiClient, Mock]:
    """Return a client that fetched Google's list once, and its fake glocaltokens."""
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    client = GlocaltokensApiClient(hass, session or Mock(), master_token=MASTER_TOKEN)
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


def update(client: GlocaltokensApiClient) -> list[GoogleHomeDevice]:
    """Run one update without asking the devices, and return its devices."""
    client.collect_data_from_endpoints = AsyncMock()  # type: ignore[method-assign]
    return asyncio.run(client.update_google_devices_information())


def test_fetch_once_a_day(clock: Mock) -> None:
    """Ask Google again a day after the last fetch, to find added and removed devices."""
    client, glocaltokens = make_client("10.0.0.2", "10.0.0.3")

    clock.return_value = FETCH_DEVICES_INTERVAL - 1
    assert fetches_in(client, glocaltokens, 3) == 0
    clock.return_value = FETCH_DEVICES_INTERVAL
    assert fetches_in(client, glocaltokens, 1) == 1
    assert fetches_in(client, glocaltokens, 3) == 1
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL - 1
    assert fetches_in(client, glocaltokens, 1) == 1
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    assert fetches_in(client, glocaltokens, 1) == 2


def test_fetch_for_missing_device_restarts_the_day(clock: Mock) -> None:
    """Count the day from the last fetch, even one made to find a missing device."""
    client, glocaltokens = make_client("10.0.0.2", None)
    # Five hours after setup, mDNS finds the missing device
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2"),
        found("device1", "10.0.0.3"),
    ]
    clock.return_value = 5 * HOUR
    assert fetches_in(client, glocaltokens, FETCH_DEVICES_EVERY) == 1

    clock.return_value = FETCH_DEVICES_INTERVAL + 5 * HOUR - 1
    assert fetches_in(client, glocaltokens, 1) == 1
    clock.return_value = FETCH_DEVICES_INTERVAL + 5 * HOUR
    assert fetches_in(client, glocaltokens, 1) == 2


@pytest.mark.parametrize("ip_addresses", [("10.0.0.2",), ()])
@pytest.mark.parametrize("homegraph_fails", [True, False])
def test_daily_fetch_fails(
    clock: Mock, ip_addresses: tuple[str, ...], homegraph_fails: bool
) -> None:
    """Keep the devices, even none, when Google can't be reached, and try again a day later.

    Trying on every update would ask Google every few minutes while it is failing.
    """
    client, glocaltokens = make_client(*ip_addresses)
    devices = list(client.google_devices)
    if homegraph_fails:
        glocaltokens.homegraph = None
    else:
        glocaltokens.get_google_devices.side_effect = RequestsConnectionError

    clock.return_value = FETCH_DEVICES_INTERVAL
    assert update(client) == devices
    assert glocaltokens.get_google_devices.call_count == 1
    assert client.google_devices_fetched

    clock.return_value = 2 * FETCH_DEVICES_INTERVAL - 1
    assert fetches_in(client, glocaltokens, 3) == 1
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    assert fetches_in(client, glocaltokens, 1) == 2


def can_delete(
    client: GlocaltokensApiClient, devices: list[GoogleHomeDevice], device_id: str
) -> bool:
    """Ask the integration whether the device with this ID can be deleted."""
    hass = Mock(
        data={
            DOMAIN: {
                "entry": {DATA_CLIENT: client, DATA_COORDINATOR: Mock(data=devices)}
            }
        }
    )
    return asyncio.run(
        async_remove_config_entry_device(
            hass, Mock(entry_id="entry"), Mock(identifiers={(DOMAIN, device_id)})
        )
    )


def test_device_google_stops_listing(clock: Mock) -> None:
    """Show a device removed in the Google Home app as unavailable, and let it be deleted.

    If Google lists it again, its entities work again without being added twice.
    """
    client, glocaltokens = make_client("10.0.0.2", "10.0.0.3")
    coordinator = Mock(data=update(client), last_update_success=True)
    listener, added = add_entities(coordinator, GoogleHomeAlarmsSensor)
    assert added() == [("device0", "alarms"), ("device1", "alarms")]
    kitchen, bedroom = (
        GoogleHomeAlarmsSensor(coordinator, client, device_id, device_id, None)
        for device_id in ("device0", "device1")
    )

    glocaltokens.get_google_devices.return_value = [found("device0", "10.0.0.2")]
    clock.return_value = FETCH_DEVICES_INTERVAL
    coordinator.data = update(client)
    listener()

    assert (kitchen.available, bedroom.available) == (True, False)
    assert can_delete(client, coordinator.data, "device1")
    assert not can_delete(client, coordinator.data, "device0")

    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2"),
        found("device1", "10.0.0.3"),
    ]
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    coordinator.data = update(client)
    listener()

    assert bedroom.available
    assert added() == []


def test_google_lists_no_devices(clock: Mock) -> None:
    """Remember that Google lists no devices rather than ask again on every update."""
    client, glocaltokens = make_client("10.0.0.2")
    # The only device is removed in the Google Home app
    glocaltokens.get_google_devices.return_value = []

    clock.return_value = FETCH_DEVICES_INTERVAL
    assert update(client) == []
    assert glocaltokens.get_google_devices.call_count == 1
    assert can_delete(client, [], "device0")

    clock.return_value = 2 * FETCH_DEVICES_INTERVAL - 1
    assert fetches_in(client, glocaltokens, 3) == 1

    # A device is added in the Google Home app
    glocaltokens.get_google_devices.return_value = [found("office", "10.0.0.4")]
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    assert [device.device_id for device in update(client)] == ["office"]
    assert glocaltokens.get_google_devices.call_count == 2


def answering(status: HTTPStatus) -> Mock:
    """Return a session to which every device answers with this HTTP status."""
    response = MagicMock()
    response.__aenter__.return_value.status = status
    return Mock(request=Mock(return_value=response))


def test_fetch_on_every_update_after_token_rejected(clock: Mock) -> None:
    """Fetch Google's list once on every update after a device rejects its token, until it works.

    Until then, the list is unknown, so no device can be deleted.
    """
    client, glocaltokens = make_client(
        "10.0.0.2", session=answering(HTTPStatus.UNAUTHORIZED)
    )
    [kitchen] = client.google_devices
    # Just when the daily fetch is due, which mustn't make it fetch twice
    clock.return_value = FETCH_DEVICES_INTERVAL
    asyncio.run(client.update_alarms_and_timers(kitchen))
    assert not can_delete(client, [kitchen], "removed")

    glocaltokens.homegraph = None
    assert fetches_in(client, glocaltokens, 3) == 3
    assert not can_delete(client, [], "removed")

    glocaltokens.homegraph = Mock()
    assert fetches_in(client, glocaltokens, 3) == 4
    assert can_delete(client, client.google_devices, "removed")


def test_keep_polled_data_when_list_fetched_again(clock: Mock) -> None:
    """Keep a device's alarms, timers and settings if it doesn't answer when Google's list is fetched.

    Otherwise it would show no alarms, Do Not Disturb off and alarm volume 0
    until it answers.
    """
    client, _ = make_client(
        "10.0.0.2", session=Mock(request=Mock(side_effect=TimeoutError))
    )
    [kitchen] = client.google_devices
    kitchen.set_alarms([{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}])
    kitchen.set_timers(
        [
            {
                "id": TIMER_ID,
                "fire_time": 1700000000000,
                "original_duration": 60000,
                "status": 1,
            }
        ]
    )
    kitchen.set_do_not_disturb(True)
    kitchen.set_alarm_volume(70)

    clock.return_value = FETCH_DEVICES_INTERVAL
    [device] = asyncio.run(client.update_google_devices_information())

    assert device is kitchen
    assert not device.available
    # Google's name, token and model replace the ones the device had
    assert (device.name, device.auth_token, device.hardware) == (
        "device0",
        LOCAL_AUTH_TOKEN,
        "Nest Audio",
    )
    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == [ALARM_ID]
    assert [timer.timer_id for timer in device.get_sorted_timers()] == [TIMER_ID]
    assert device.get_do_not_disturb()
    assert device.get_alarm_volume() == 70


def test_add_entities_for_device_added_in_google_home_app(clock: Mock) -> None:
    """Add entities for a device that the daily fetch finds, without a reload."""
    client, glocaltokens = make_client("10.0.0.2")
    coordinator = Mock(data=update(client))
    listener, added = add_entities(coordinator, GoogleHomeAlarmsSensor)
    assert added() == [("device0", "alarms")]

    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2"),
        found("office", "10.0.0.4"),
    ]
    clock.return_value = FETCH_DEVICES_INTERVAL
    coordinator.data = update(client)
    listener()

    assert added() == [("office", "alarms")]


def fetch(client: GlocaltokensApiClient) -> None:
    """Run the update on which Google's list is fetched again."""
    client.updates_until_fetch = 1
    asyncio.run(client.async_fetch_devices_when_due())


def test_keep_address_mdns_missed() -> None:
    """Keep the address of a device that mDNS found before but missed this time.

    An address that mDNS finds replaces the old one, as the device may have moved.
    """
    client, glocaltokens = make_client("10.0.0.2", None, "10.0.0.4")
    glocaltokens.get_google_devices.return_value = [
        found("device0", None),
        found("device1", "10.0.0.3"),
        found("device2", "10.0.0.5"),
    ]

    fetch(client)

    assert [device.ip_address for device in client.google_devices] == [
        "10.0.0.2",
        "10.0.0.3",
        "10.0.0.5",
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
