"""Tests for fetching Google's device list again after setup."""

import asyncio
from collections.abc import AsyncIterator, Callable
import contextlib
from http import HTTPStatus
import logging
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

from glocaltokens.client import Device
from glocaltokens.exceptions import AuthenticationError, HomegraphError
from glocaltokens.scanner import NetworkDevice
import grpc  # type: ignore[import-untyped]
import pytest
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError, HTTPError

from custom_components.google_home import (
    async_remove_config_entry_device,
    async_setup_entry,
    async_update_devices,
)
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    DOMAIN,
    FETCH_DEVICES_INTERVAL,
)
from custom_components.google_home.entity import async_add_device_entities
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeTimersSensor,
)
from custom_components.google_home.types import GoogleHomeConfigEntry, GoogleHomeData

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import SOURCE_USER, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .test_entity import home_assistant

# pylint: enable=wrong-import-order

# A realistic master token: setup checks its length with is_aas_et()
MASTER_TOKEN = "aas_et/" + "x" * 216
# glocaltokens returns only devices whose local auth token has this length
LOCAL_AUTH_TOKEN = "x" * 108
ALARM_ID = "alarm/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51"
TIMER_ID = "timer/6ed06a56-8a58-c6e3-a7d4-03f92c9d8a51"
MINUTE = 60
HOUR = 60 * MINUTE


def answered(status: HTTPStatus) -> HTTPError:
    """Return the error glocaltokens raises when Google answers with this status."""
    response = Response()
    response.status_code = status
    return HTTPError(response=response)


# What glocaltokens raises when Google doesn't give the list, other than when its
# sign-in can't be reached
FETCH_ERRORS = [
    pytest.param(
        HomegraphError(grpc.StatusCode.UNAVAILABLE, "The service is unavailable."),
        id="no-home-graph",
    ),
    pytest.param(
        AuthenticationError("Google gave no access token", "BadAuthentication"),
        id="token-rejected",
    ),
    pytest.param(answered(HTTPStatus.SERVICE_UNAVAILABLE), id="http-503"),
    pytest.param(answered(HTTPStatus.TOO_MANY_REQUESTS), id="http-429"),
]
UNREACHABLE = pytest.param(RequestsConnectionError(), id="unreachable")
# The errors that say nothing about the master token
NOT_REJECTED = [error for error in FETCH_ERRORS if error.id != "token-rejected"]


def rejected() -> AuthenticationError:
    """Return what glocaltokens raises when Google rejects the master token."""
    return AuthenticationError("Google gave no access token", "BadAuthentication")


# What the integration logs when Google rejects the master token
REJECTED_LOG = (
    "Failed to fetch Google's device list: Google gave no access token: "
    "BadAuthentication"
)


def logged(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    """Return the level and message of each line the integration logged."""
    return [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name == "custom_components.google_home"
    ]


def found(
    device_id: str,
    ip_address: str | None,
    token: str = LOCAL_AUTH_TOKEN,
    name: str | None = None,
    cloud_device_id: str | None = None,
) -> Device:
    """Return a device as glocaltokens returns it, with the address mDNS found.

    Its name and Google's other ID for it are its ID unless given.
    """
    name = name or device_id
    cloud_device_id = cloud_device_id or device_id
    network_device = (
        NetworkDevice(name, ip_address, 8009, "Nest Audio", cloud_device_id)
        if ip_address
        else None
    )
    return Device(
        device_id,
        name,
        token,
        network_device,
        hardware="Nest Audio",
        cloud_device_id=cloud_device_id,
    )


async def until(condition: Callable[[], bool]) -> None:
    """Let the other tasks run until the condition holds.

    The fake devices and Google answer without letting other tasks run, so this
    sets the order in which overlapping requests and fetches meet.
    """
    async with asyncio.timeout(1):
        while not condition():
            await asyncio.sleep(0)


def make_client(
    *ip_addresses: str | None,
    session: Mock | None = None,
    google_answers_when: Callable[[], bool] | None = None,
) -> tuple[GlocaltokensApiClient, Mock]:
    """Return a client that fetched Google's list once, and its fake glocaltokens.

    With google_answers_when, a fetch of Google's list waits until it holds.
    """

    async def executor(func: Callable[[], object]) -> object:
        if google_answers_when is not None:
            await until(google_answers_when)
        return func()

    hass = Mock()
    hass.async_add_executor_job = AsyncMock(side_effect=executor)
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


def update(client: GlocaltokensApiClient) -> list[GoogleHomeDevice]:
    """Run one update without asking the devices, and return its devices."""
    client.collect_data_from_endpoints = AsyncMock()  # type: ignore[method-assign]
    return asyncio.run(client.update_google_devices_information())


@pytest.mark.parametrize(
    ("interval", "expected"),
    [
        (30, [20 * MINUTE, 40 * MINUTE, HOUR]),
        # The first update 20 minutes after the last fetch is the seventh
        (180, [21 * MINUTE, 42 * MINUTE]),
    ],
)
@pytest.mark.parametrize("ip_addresses", [("10.0.0.2", "10.0.0.3"), ("10.0.0.2", None)])
def test_fetch_every_20_minutes(
    clock: Mock,
    ip_addresses: tuple[str | None, ...],
    interval: int,
    expected: list[int],
) -> None:
    """Ask Google again 20 minutes after the last fetch, however often the devices are updated.

    That finds devices added in or removed from the Google Home app, and the
    address of a device that was offline, without asking more often while a
    device has no address. The 20 minutes are written out, not taken from the
    constant, so the test also catches a change to how often the integration asks.
    """
    client, glocaltokens = make_client(*ip_addresses)

    fetched_at: list[int] = []
    # Update at this interval for an hour after setup
    for seconds in range(interval, HOUR + 1, interval):
        clock.return_value = seconds
        fetches = glocaltokens.get_google_devices.call_count
        update(client)
        if glocaltokens.get_google_devices.call_count > fetches:
            fetched_at.append(seconds)

    assert fetched_at == expected


@pytest.mark.parametrize("ip_addresses", [("10.0.0.2",), ()])
@pytest.mark.parametrize("error", [*FETCH_ERRORS, UNREACHABLE])
def test_scheduled_fetch_fails(
    clock: Mock, ip_addresses: tuple[str, ...], error: Exception
) -> None:
    """Keep the devices, even none, when Google's list can't be fetched, and try again 20 minutes later.

    Trying on every update would ask Google as often as the devices update while it
    is failing.
    """
    client, glocaltokens = make_client(*ip_addresses)
    devices = list(client.google_devices)
    glocaltokens.get_google_devices.side_effect = error

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
    entry = Mock(
        state=ConfigEntryState.LOADED,
        runtime_data=GoogleHomeData(client, Mock(data=devices)),
    )
    return asyncio.run(
        async_remove_config_entry_device(
            Mock(), entry, Mock(identifiers={(DOMAIN, device_id)})
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
    """Return a session to which every device answers with this HTTP status, also when asked for its info."""
    response = MagicMock()
    response.__aenter__.return_value.status = status
    return Mock(request=Mock(return_value=response), get=Mock(return_value=response))


def fetch_times(
    client: GlocaltokensApiClient, glocaltokens: Mock, clock: Mock, start: int
) -> list[int]:
    """Update every 15 seconds for an hour from start, asking the devices, and return when Google's list was fetched.

    An update that fetches the list fails when Google can't be reached.
    """
    fetched_at: list[int] = []
    for seconds in range(start, start + HOUR + 1, 15):
        clock.return_value = seconds
        fetches = glocaltokens.get_google_devices.call_count
        with contextlib.suppress(RequestsConnectionError):
            asyncio.run(client.update_google_devices_information())
        if glocaltokens.get_google_devices.call_count > fetches:
            fetched_at.append(seconds)
    return fetched_at


# When Google's list is fetched while it is unknown and every fetch fails, in minutes
# after the first failure: 1, 2, 5, 10, 20 and 20 minutes apart. Written out, not
# taken from the constants, so the test also catches a change to them.
RETRY_MINUTES = (0, 1, 3, 8, 18, 38, 58)


@pytest.mark.parametrize("error", [*FETCH_ERRORS, UNREACHABLE])
def test_fetch_less_often_while_list_unknown_after_token_rejected(
    clock: Mock, error: Exception
) -> None:
    """Wait longer and longer between fetches of Google's list while it is unknown and can't be fetched.

    After a device rejects even its new token, the list is unknown. Each update
    would otherwise fetch it while Google fails: at its start, and again when the
    device rejects its token, which the device does on every update until Google
    gives it a new one. Until a fetch works, no device can be deleted.
    """
    client, glocaltokens = make_client(
        "10.0.0.2", session=answering(HTTPStatus.UNAUTHORIZED)
    )
    [kitchen] = client.google_devices
    asyncio.run(client.update_alarms_and_timers(kitchen))
    # The rejection fetched the list straight away
    assert glocaltokens.get_google_devices.call_count == 1
    assert not client.google_devices_fetched

    glocaltokens.get_google_devices.side_effect = error

    assert fetch_times(client, glocaltokens, clock, 15) == [
        15 + minutes * MINUTE for minutes in RETRY_MINUTES
    ]
    assert not can_delete(client, [kitchen], "removed")


@pytest.mark.parametrize("error", NOT_REJECTED)
def test_fetch_less_often_after_setup_without_devices(
    clock: Mock, error: Exception
) -> None:
    """Wait longer and longer between fetches of Google's list after setup couldn't fetch it.

    Setup then goes on without devices, and the list is unknown until a fetch works.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = error

    assert fetch_times(client, glocaltokens, clock, 0) == [
        minutes * MINUTE for minutes in RETRY_MINUTES
    ]


def test_unreachable_at_setup() -> None:
    """Fail the update when Google's sign-in can't be reached before the list is known.

    At setup, Home Assistant then tries setting up the integration again.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = RequestsConnectionError

    with pytest.raises(RequestsConnectionError):
        update(client)


HASS = Mock()


def update_entry(client: GlocaltokensApiClient, entry: Mock) -> list[GoogleHomeDevice]:
    """Run one update as the coordinator does, and return its devices.

    The devices aren't asked, but the update must still reach them.
    """
    client.collect_data_from_endpoints = AsyncMock()  # type: ignore[method-assign]
    devices = asyncio.run(async_update_devices(HASS, entry, client))
    client.collect_data_from_endpoints.assert_has_awaits(
        [call(device) for device in devices if device.ip_address]
    )
    return devices


def test_sign_in_rejected_at_setup() -> None:
    """Fail setup with Google's reason when it rejects the master token.

    Home Assistant then asks to sign in again, as there are no devices to keep.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = rejected()
    entry = Mock()

    with pytest.raises(ConfigEntryAuthFailed, match="BadAuthentication"):
        update_entry(client, entry)
    # Home Assistant starts it for a failed setup
    entry.async_start_reauth.assert_not_called()


@contextlib.asynccontextmanager
async def set_up(
    tmp_path: Path, google: Mock
) -> AsyncIterator[tuple[HomeAssistant, GoogleHomeConfigEntry]]:
    """Set up the integration as Home Assistant does, with google as glocaltokens' fetch of the list.

    Raise what setup raises, or yield Home Assistant and the entry. Home Assistant's
    first update of the devices is real; loading the platforms is left out.
    """
    async with home_assistant(tmp_path) as (hass, _):
        entry: GoogleHomeConfigEntry = ConfigEntry(
            data={CONF_MASTER_TOKEN: MASTER_TOKEN, CONF_ANDROID_ID: "android-id"},
            discovery_keys=MappingProxyType({}),
            domain=DOMAIN,
            minor_version=2,
            options={},
            source=SOURCE_USER,
            subentries_data=None,
            title="test@example.com",
            unique_id=None,
            version=1,
            # The first update checks that it runs during setup
            state=ConfigEntryState.SETUP_IN_PROGRESS,
        )
        with (
            patch("custom_components.google_home.zeroconf.async_get_instance"),
            # Browsing needs a real zeroconf instance
            patch("custom_components.google_home.async_browse_cast_devices"),
            patch("custom_components.google_home.async_get_clientsession"),
            patch.object(hass.config_entries, "async_forward_entry_setups"),
            patch(
                "glocaltokens.client.GLocalAuthenticationTokens.get_google_devices",
                google,
            ),
        ):
            await async_setup_entry(hass, entry)
            yield hass, entry


def test_setup_leaves_rejected_master_token_to_home_assistant(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Fail setup with Google's reason when it rejects the master token, and log it only for debugging.

    Home Assistant logs why setup fails as a warning, with that reason, so an error
    from the integration would say the same thing twice.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")

    async def run() -> None:
        async with set_up(tmp_path, Mock(side_effect=rejected())):
            pass

    with pytest.raises(ConfigEntryAuthFailed) as err:
        asyncio.run(run())

    # What Home Assistant logs after "could not authenticate: "
    assert str(err.value) == "Google gave no access token: BadAuthentication"
    lines = logged(caplog)
    assert ("DEBUG", REJECTED_LOG) in lines
    assert [line for line in lines if line[0] not in {"DEBUG", "INFO"}] == []


@pytest.mark.parametrize("error", NOT_REJECTED)
def test_setup_logs_other_fetch_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """Log why Google's list can't be fetched at setup for another reason, as setup goes on without devices.

    Home Assistant logs nothing then.
    """

    async def run() -> None:
        async with set_up(tmp_path, Mock(side_effect=error)):
            pass

    asyncio.run(run())

    assert ("ERROR", f"Failed to fetch Google's device list: {error}") in logged(caplog)


def test_log_sign_in_rejected_after_setup(
    clock: Mock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token once setup is done.

    Only setup leaves that to Home Assistant: later it asks to sign in again
    without saying why.
    """
    # A device without an address, which no update asks
    google = Mock(return_value=[found("device0", None)])

    async def run() -> None:
        async with set_up(tmp_path, google) as (_, entry):
            client = entry.runtime_data.client
            google.side_effect = rejected()
            # The scheduled fetch is due
            clock.return_value = FETCH_DEVICES_INTERVAL
            await client.update_google_devices_information()

    asyncio.run(run())

    assert google.call_count == 2
    assert ("ERROR", REJECTED_LOG) in logged(caplog)


def test_sign_in_rejected_with_devices(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Ask to sign in again when Google rejects the master token, log why, and keep updating the devices.

    Devices may still accept the local tokens they got earlier. Home Assistant
    doesn't log why it asks to sign in, so the integration does.
    """
    client, glocaltokens = make_client("10.0.0.2", None)
    devices = list(client.google_devices)
    glocaltokens.get_google_devices.side_effect = rejected()
    entry = Mock()

    clock.return_value = FETCH_DEVICES_INTERVAL
    assert update_entry(client, entry) == devices

    assert glocaltokens.get_google_devices.call_count == 1
    entry.async_start_reauth.assert_called_once_with(HASS)
    assert ("ERROR", REJECTED_LOG) in logged(caplog)


def test_log_sign_in_rejected_after_failed_update(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token after setup, even without devices.

    The update then fails, but after an update that failed because Google couldn't
    be reached, Home Assistant doesn't log that it failed again, so the integration
    does, with Google's reason.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    entry = Mock()
    glocaltokens.get_google_devices.side_effect = RequestsConnectionError
    with pytest.raises(RequestsConnectionError):
        update_entry(client, entry)

    glocaltokens.get_google_devices.side_effect = rejected()
    clock.return_value = MINUTE
    with pytest.raises(ConfigEntryAuthFailed):
        update_entry(client, entry)

    assert ("ERROR", REJECTED_LOG) in logged(caplog)


@pytest.mark.parametrize("ip_addresses", [("10.0.0.2",), ()])
@pytest.mark.parametrize("error", [*NOT_REJECTED, UNREACHABLE])
def test_other_fetch_errors_dont_ask_to_sign_in(
    clock: Mock, ip_addresses: tuple[str, ...], error: Exception
) -> None:
    """Don't ask to sign in again when Google's list can't be fetched for another reason."""
    client, glocaltokens = make_client(*ip_addresses)
    glocaltokens.get_google_devices.side_effect = error
    entry = Mock()

    clock.return_value = FETCH_DEVICES_INTERVAL
    update_entry(client, entry)

    assert glocaltokens.get_google_devices.call_count == 1
    entry.async_start_reauth.assert_not_called()


@pytest.mark.parametrize("error", NOT_REJECTED)
def test_other_fetch_errors_at_setup_dont_ask_to_sign_in(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """Set up without devices when Google's list can't be fetched for another reason, and log why."""
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = error
    entry = Mock()

    assert update_entry(client, entry) == []

    entry.async_start_reauth.assert_not_called()
    assert ("ERROR", f"Failed to fetch Google's device list: {error}") in logged(caplog)


def test_ask_to_sign_in_until_fetch_works(clock: Mock) -> None:
    """Keep asking to sign in again on each update until Google's list is fetched.

    Home Assistant ignores the request while the sign-in is open, so it comes back
    only after a sign-in ends without success, such as after the different account
    message. Errors that say nothing about the master token don't stop the asking.
    """
    client, glocaltokens = make_client("10.0.0.2")
    glocaltokens.get_google_devices.side_effect = rejected()
    entry = Mock()

    def asks_after(seconds: int, error: Exception | None = None) -> bool:
        clock.return_value = seconds
        if error is not None:
            glocaltokens.get_google_devices.side_effect = error
        entry.async_start_reauth.reset_mock()
        update_entry(client, entry)
        return bool(entry.async_start_reauth.called)

    assert asks_after(FETCH_DEVICES_INTERVAL)
    # An update that doesn't fetch the list
    assert asks_after(FETCH_DEVICES_INTERVAL + 1)
    # Fetches that fail for other reasons
    assert asks_after(2 * FETCH_DEVICES_INTERVAL, RequestsConnectionError())
    assert asks_after(
        3 * FETCH_DEVICES_INTERVAL, answered(HTTPStatus.SERVICE_UNAVAILABLE)
    )
    assert glocaltokens.get_google_devices.call_count == 3

    glocaltokens.get_google_devices.side_effect = None
    assert not asks_after(4 * FETCH_DEVICES_INTERVAL)
    assert not asks_after(4 * FETCH_DEVICES_INTERVAL + 1)
    assert glocaltokens.get_google_devices.call_count == 4


def test_ask_to_sign_in_after_failed_update(clock: Mock) -> None:
    """Ask to sign in again on the update after one that fails.

    After a device rejects its token, updates fetch Google's list until it works,
    and an update that fetches it fails when Google can't be reached. Google's
    earlier rejection still stands, so the next update that works asks to sign in
    again.
    """
    client, glocaltokens = make_client(
        "10.0.0.2", session=answering(HTTPStatus.UNAUTHORIZED)
    )
    [kitchen] = client.google_devices
    glocaltokens.get_google_devices.side_effect = rejected()
    entry = Mock()
    clock.return_value = FETCH_DEVICES_INTERVAL
    update_entry(client, entry)
    asyncio.run(client.update_alarms_and_timers(kitchen))
    entry.async_start_reauth.reset_mock()

    # Once the wait after the failed fetch has passed
    clock.return_value = FETCH_DEVICES_INTERVAL + MINUTE
    glocaltokens.get_google_devices.side_effect = RequestsConnectionError
    with pytest.raises(RequestsConnectionError):
        update_entry(client, entry)
    entry.async_start_reauth.assert_not_called()

    clock.return_value = FETCH_DEVICES_INTERVAL + 3 * MINUTE
    glocaltokens.get_google_devices.side_effect = answered(
        HTTPStatus.SERVICE_UNAVAILABLE
    )
    assert update_entry(client, entry) == [kitchen]
    entry.async_start_reauth.assert_called_once_with(HASS)


def test_keep_polled_data_after_token_rejected() -> None:
    """Keep the data of the other devices when Google's list is fetched after a device rejects its token.

    The fetch gives new tokens, but a device that doesn't answer that update
    would otherwise show no alarms, Do Not Disturb off and alarm volume 0.
    """
    session = answering(HTTPStatus.UNAUTHORIZED)
    client, glocaltokens = make_client("10.0.0.2", "10.0.0.3", session=session)
    kitchen, bedroom = client.google_devices
    bedroom.set_alarms([{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}])
    bedroom.set_do_not_disturb(True)
    bedroom.set_alarm_volume(70)
    # The rejection fetches the list straight away, and the kitchen rejects its
    # new token too, so the next update fetches it again
    asyncio.run(client.update_alarms_and_timers(kitchen))

    # Google lists both devices again, and neither answers this update
    session.request.side_effect = TimeoutError
    assert asyncio.run(client.update_google_devices_information()) == [
        kitchen,
        bedroom,
    ]

    assert glocaltokens.get_google_devices.call_count == 2
    assert bedroom.auth_token == LOCAL_AUTH_TOKEN
    assert [alarm.alarm_id for alarm in bedroom.get_sorted_alarms()] == [ALARM_ID]
    assert bedroom.get_do_not_disturb()
    assert bedroom.get_alarm_volume() == 70


def test_keep_polled_data_when_list_fetched_again(clock: Mock) -> None:
    """Keep a device's alarms, timers and settings if it doesn't answer when Google's list is fetched.

    Otherwise it would show no alarms, Do Not Disturb off and alarm volume 0
    until it answers.
    """
    client, _ = make_client(
        "10.0.0.2",
        session=Mock(
            request=Mock(side_effect=TimeoutError), get=Mock(side_effect=TimeoutError)
        ),
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
    """Add entities for a device that a scheduled fetch finds, without a reload."""
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


def fetch(client: GlocaltokensApiClient, clock: Mock) -> None:
    """Run the update on which Google's list is fetched again."""
    clock.return_value = FETCH_DEVICES_INTERVAL
    asyncio.run(client.async_fetch_devices_when_due())


def test_keep_address_mdns_missed(clock: Mock) -> None:
    """Keep the address of a device that mDNS found before but missed this time.

    An address that mDNS finds replaces the old one, as the device may have moved.
    """
    client, glocaltokens = make_client("10.0.0.2", None, "10.0.0.4")
    glocaltokens.get_google_devices.return_value = [
        found("device0", None),
        found("device1", "10.0.0.3"),
        found("device2", "10.0.0.5"),
    ]

    fetch(client, clock)

    assert [device.ip_address for device in client.google_devices] == [
        "10.0.0.2",
        "10.0.0.3",
        "10.0.0.5",
    ]


@pytest.mark.parametrize("error", [*FETCH_ERRORS, UNREACHABLE])
def test_keep_devices_when_fetch_fails(clock: Mock, error: Exception) -> None:
    """Keep the devices of the last fetch when Google's list can't be fetched."""
    client, glocaltokens = make_client("10.0.0.2", None)
    devices = list(client.google_devices)
    glocaltokens.get_google_devices.side_effect = error

    fetch(client, clock)

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
        Mock(runtime_data=GoogleHomeData(Mock(), coordinator)),
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
