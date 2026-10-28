"""Tests for finding devices with mDNS between fetches of Google's device list.

Times are seconds since setup fetched the list. Google's list is fetched again 20
minutes after the last fetch started, and 30 seconds after mDNS first finds a device
that the list doesn't have, but no sooner than 5 minutes after the last fetch for
such devices started.
"""

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
import logging
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from glocaltokens.client import Device
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import HEADER_CAST_LOCAL_AUTH
from custom_components.google_home.models import GoogleHomeDevice

from .test_missing_devices import LOCAL_AUTH_TOKEN, MASTER_TOKEN, answered, found, until


@dataclass
class Timer:
    """A timer that the client set, as Home Assistant's async_call_later would."""

    at: float
    action: Callable[[datetime], None]
    cancelled: bool = False
    fired: bool = False

    def cancel(self) -> None:
        """Cancel the timer."""
        self.cancelled = True


@pytest.fixture(name="timers")
def fixture_timers(clock: Mock) -> Iterator[list[Timer]]:
    """Record the timers the client sets, at the client's clock."""
    timers: list[Timer] = []

    def call_later(
        _hass: object, delay: float, action: Callable[[datetime], None]
    ) -> Callable[[], None]:
        timer = Timer(float(clock.return_value) + delay, action)
        timers.append(timer)
        return timer.cancel

    with patch(
        "custom_components.google_home.mdns.async_call_later", side_effect=call_later
    ):
        yield timers


@dataclass
class Network:
    """Google, the devices, and Home Assistant's timers and updates around a client."""

    clock: Mock
    timers: list[Timer]
    listed: list[Device]
    session: Mock = field(default_factory=Mock)
    known_hosts: list[str] = field(default_factory=list)
    # What Google raises instead of answering
    error: Exception | None = None
    # When each fetch of Google's list started
    fetches: list[float] = field(default_factory=list)
    # Whether Google answers now, or the fetch waits
    google_answers: bool = True
    # Whether the devices answer now, or the update waits
    devices_answer: bool = True
    # Each device that an update asked, with the address it was asked at
    polled: list[tuple[str, str | None]] = field(default_factory=list)
    # How often the client asked for an update, and whether that runs one
    requests: int = 0
    request_runs_update: bool = True
    # Whether updates ask the devices for their alarms and timers for real
    real_polling: bool = False
    tasks: list[asyncio.Task[None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Create the client as setup does, before setup fetches the list."""
        hass = Mock()
        hass.async_add_executor_job = AsyncMock(side_effect=self._executor)
        hass.async_create_background_task = Mock(side_effect=self._create_task)
        self.client = GlocaltokensApiClient(
            hass,
            self.session,
            master_token=MASTER_TOKEN,
            known_hosts=self.known_hosts,
        )
        self.client._client = Mock(  # noqa: SLF001  # pylint: disable=protected-access
            get_google_devices=Mock(side_effect=self._get_google_devices)
        )
        self.client.collect_data_from_endpoints = AsyncMock(  # type: ignore[method-assign]
            side_effect=self._poll
        )
        self.client.found_devices.request_update = self._request_update
        self._lock: asyncio.Lock | None = None

    async def _executor(self, func: Callable[[], object]) -> object:
        self.fetches.append(float(self.clock.return_value))
        await until(lambda: self.google_answers)
        return func()

    def _get_google_devices(self, **_kwargs: object) -> list[Device]:
        if self.error is not None:
            raise self.error
        return list(self.listed)

    def _create_task(
        self, target: Coroutine[object, object, None], _name: str, **_kwargs: object
    ) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(target)
        self.tasks.append(task)
        return task

    async def _poll(self, device: GoogleHomeDevice) -> GoogleHomeDevice:
        await until(lambda: self.devices_answer)
        self.polled.append((device.device_id, device.ip_address))
        if self.real_polling:
            return await self.client.update_alarms_and_timers(device)
        return device

    async def _request_update(self) -> None:
        self.requests += 1
        if self.request_runs_update:
            await self.update()

    async def update(self, at: float | None = None) -> None:
        """Run an update, one at a time as the coordinator does."""
        if at is not None:
            self.clock.return_value = at
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            await self.client.update_google_devices_information()

    async def setup(self) -> None:
        """Fetch the list as setup does."""
        self.clock.return_value = 0
        await self.client.get_google_devices()

    def report(self, cloud_device_id: str, address: str, at: float) -> None:
        """Report a device as mDNS finds it."""
        self.clock.return_value = at
        self.client.found_devices.async_device_found(
            cloud_device_id, cloud_device_id, address
        )

    def live(self) -> list[float]:
        """Return when each timer that is set fires."""
        return [
            timer.at for timer in self.timers if not timer.cancelled and not timer.fired
        ]

    async def fire(self, timer: Timer) -> None:
        """Fire a timer at its time, even a cancelled one, and let what it starts run."""
        self.clock.return_value = timer.at
        timer.fired = True
        timer.action(datetime.now())
        await settle()

    async def fire_due(self) -> None:
        """Fire the one timer that is set."""
        [timer] = [t for t in self.timers if not t.cancelled and not t.fired]
        await self.fire(timer)

    async def fetch_due_at(self, at: float) -> None:
        """Check that the first update at or after this time fetches the list, and not one just before."""
        fetches = list(self.fetches)
        await self.update(at - 1)
        assert self.fetches == fetches
        await self.update(at)
        assert self.fetches == [*fetches, at]

    def device(self, device_id: str) -> GoogleHomeDevice:
        """Return a device in the client's list."""
        [device] = [d for d in self.client.google_devices if d.device_id == device_id]
        return device


async def settle() -> None:
    """Let started tasks run until they wait."""
    for _ in range(20):
        await asyncio.sleep(0)


async def held_fetch(network: Network, at: float) -> asyncio.Task[None]:
    """Start the update at this time whose fetch of Google's list waits for an answer."""
    network.google_answers = False
    fetches = len(network.fetches)
    task = asyncio.ensure_future(network.update(at))
    await until(lambda: len(network.fetches) > fetches)
    return task


def test_known_device_gets_address_without_fetch(
    clock: Mock, timers: list[Timer]
) -> None:
    """Give a listed device that mDNS finds its address, and ask it at the next update, without asking Google.

    One device was offline at setup and has no address; the other moved.
    """
    network = Network(
        clock, timers, [found("kitchen", None), found("office", "10.0.0.3")]
    )

    async def run() -> None:
        await network.setup()
        network.report("kitchen", "10.0.0.2", at=100)
        network.report("office", "10.0.0.4", at=101)
        assert network.live() == []
        await network.update(180)

    asyncio.run(run())
    assert network.fetches == [0]
    assert network.polled == [("kitchen", "10.0.0.2"), ("office", "10.0.0.4")]


def test_new_device_fetched_and_asked(clock: Mock, timers: list[Timer]) -> None:
    """Fetch the list 30 seconds after mDNS finds a device it doesn't have, and ask the device in that update.

    The scan of that fetch misses the device, so it uses the address that mDNS
    reported, without asking the known hosts.
    """
    session = MagicMock()
    network = Network(
        clock, timers, [found("kitchen", "10.0.0.2")], session, ["10.0.1.9"]
    )

    async def run() -> None:
        await network.setup()
        network.report("office", "10.0.0.7", at=100)
        assert network.live() == [130]
        network.listed.append(found("office", None))
        await network.fire_due()

    asyncio.run(run())
    assert network.fetches == [0, 130]
    assert ("office", "10.0.0.7") in network.polled
    session.get.assert_not_called()


@pytest.mark.parametrize(
    ("outcome", "fetches", "next_fetch"),
    [
        # The fetch covered office: nothing more until the scheduled fetch
        ("listed", [0, 1200], 2400),
        # Office was found after Google was asked, so it gets a fetch of its own
        ("unlisted", [0, 1200, 1231], 2431),
        # A failed fetch is retried as scheduled, without a fetch for found devices
        ("failed", [0, 1200], 2400),
        ("unreachable", [0, 1200], 2400),
    ],
)
def test_device_found_while_fetching(
    clock: Mock,
    timers: list[Timer],
    outcome: str,
    fetches: list[float],
    next_fetch: float,
) -> None:
    """Fetch for a device found during a fetch only if that fetch worked and didn't list it."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        task = await held_fetch(network, 1200)
        network.report("office", "10.0.0.7", at=1201)
        if outcome == "listed":
            network.listed.append(found("office", None))
        elif outcome == "failed":
            network.error = answered(HTTPStatus.SERVICE_UNAVAILABLE)
        elif outcome == "unreachable":
            network.error = RequestsConnectionError()
        network.google_answers = True
        await task
        network.error = None
        for timer in list(network.timers):
            await network.fire(timer)
        await asyncio.gather(*network.tasks)
        assert network.fetches == fetches
        await network.fetch_due_at(next_fetch)

    asyncio.run(run())


def test_rejected_token_fetch_covers_found_device(
    clock: Mock, timers: list[Timer]
) -> None:
    """Don't fetch for a found device when a fetch for a rejected token already did.

    The device rejects the new token too, so every update fetches the list as
    before, but the found device's timer starts nothing.
    """
    response = MagicMock()
    response.__aenter__.return_value.status = HTTPStatus.UNAUTHORIZED
    session = Mock(request=Mock(return_value=response))
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")], session)
    network.real_polling = True

    async def run() -> None:
        await network.setup()
        network.report("office", "10.0.0.7", at=600)
        [timer] = network.timers
        assert timer.at == 630
        await network.update(610)
        assert network.fetches == [0, 610]
        assert not network.client.google_devices_fetched
        await network.fire(timer)
        assert network.requests == 0
        assert network.live() == []
        await network.update(700)

    asyncio.run(run())
    assert network.fetches == [0, 610, 700]


def test_unlisted_device_fetched_for_once(clock: Mock, timers: list[Timer]) -> None:
    """Fetch for a device that Google doesn't list only once, however often mDNS reports it.

    A TV of another account, for example, announces itself whenever it starts casting.
    """
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        network.report("tv", "10.0.0.9", at=100)
        await network.fire_due()
        await asyncio.gather(*network.tasks)
        network.report("tv", "10.0.0.9", at=500)
        network.report("tv", "10.0.0.10", at=1000)
        assert network.live() == []
        # The fetch for the TV at 130 moved the scheduled one to 1330
        await network.fetch_due_at(1330)
        network.report("tv", "10.0.0.9", at=1400)
        assert network.live() == []

    asyncio.run(run())
    assert network.fetches == [0, 130, 1330]


def test_devices_found_together_share_a_fetch(clock: Mock, timers: list[Timer]) -> None:
    """Fetch once for devices found within 30 seconds, 30 seconds after the first."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        network.report("office", "10.0.0.7", at=100)
        network.report("bedroom", "10.0.0.8", at=110)
        assert network.live() == [130]
        await network.fire_due()
        assert network.live() == []

    asyncio.run(run())
    assert network.fetches == [0, 130]


def test_devices_found_before_setup_fetch(clock: Mock, timers: list[Timer]) -> None:
    """Need no fetch for devices that mDNS knew before setup, when setup's fetch doesn't list them.

    One whose lookup ends while setup is fetching gets one fetch of its own.
    """
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        network.report("tv", "10.0.0.9", at=0)
        network.google_answers = False
        task = asyncio.ensure_future(network.setup())
        await until(lambda: len(network.fetches) == 1)
        network.report("speaker-pair", "10.0.0.10", at=2)
        network.google_answers = True
        await task
        assert network.live() == [32]
        await network.fire_due()
        await asyncio.gather(*network.tasks)
        assert network.live() == []
        await network.fetch_due_at(1232)

    asyncio.run(run())
    assert network.fetches == [0, 32, 1232]


def test_log_missing_device_only_once_list_is_known(
    clock: Mock, timers: list[Timer], caplog: pytest.LogCaptureFixture
) -> None:
    """Log that Google's list doesn't have a device only once a fetch has shown that.

    mDNS reports the devices it knows as soon as setup starts listening, before the
    list is known, and those include devices that Google lists.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        network.report("kitchen", "10.0.0.2", at=0)
        network.report("tv", "10.0.0.9", at=0)
        await network.setup()
        network.report("office", "10.0.0.7", at=100)

    asyncio.run(run())
    assert "mDNS found kitchen at 10.0.0.2" in caplog.messages
    assert "mDNS found tv at 10.0.0.9" in caplog.messages
    assert (
        "mDNS found office at 10.0.0.7, which isn't in Google's device list"
        in caplog.messages
    )
    missing = [message for message in caplog.messages if "doesn't have" in message]
    assert missing == ["Google's device list doesn't have tv, which mDNS found"]
    assert not [
        message
        for message in caplog.messages
        if "kitchen" in message and "isn't in" in message
    ]


def test_due_while_update_runs(clock: Mock, timers: list[Timer]) -> None:
    """Ask for one update when the fetch is due while an update runs, and fetch once it can.

    The update that runs started before the fetch was due, so it doesn't fetch.
    """
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        await network.update(1200)
        network.report("office", "10.0.0.7", at=1201)
        [timer] = network.timers
        assert timer.at == 1231
        network.devices_answer = False
        running = asyncio.ensure_future(network.update(1225))
        await settle()
        await network.fire(timer)
        assert network.requests == 1
        # However long the update runs, nothing asks again
        for stale in list(network.timers):
            await network.fire(stale)
        await settle()
        assert network.requests == 1
        assert network.live() == []
        assert network.fetches == [0, 1200]
        network.clock.return_value = 1240
        network.devices_answer = True
        await running
        await asyncio.gather(*network.tasks)
        assert network.fetches == [0, 1200, 1240]
        assert network.requests == 1
        assert network.live() == []
        await network.fetch_due_at(2440)

    asyncio.run(run())


def test_requested_update_doesnt_run(clock: Mock, timers: list[Timer]) -> None:
    """Don't ask again when the requested update doesn't run, as when Home Assistant stops.

    The next update at the update interval fetches for the found device instead.
    """
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])
    network.request_runs_update = False

    async def run() -> None:
        await network.setup()
        await network.update(1200)
        network.report("office", "10.0.0.7", at=1201)
        await network.fire_due()
        await asyncio.gather(*network.tasks)
        assert network.requests == 1
        assert network.live() == []
        assert network.fetches == [0, 1200]
        # The next update, 180 seconds after the one at 1231
        await network.update(1411)
        assert network.live() == []

    asyncio.run(run())
    assert network.fetches == [0, 1200, 1411]
    assert network.requests == 1


@pytest.mark.parametrize(
    ("removal", "found_at", "fetches"),
    [
        ("scheduled", 1300, [0, 1200, 1330]),
        # Reported while the fetch that drops the device runs, before its list arrives
        ("while fetching", 1300, [0, 1200, 1330]),
        # Within 5 minutes of the fetch for the TV at 230
        ("discovery", 300, [0, 230, 530]),
    ],
)
def test_removed_device_found_again(
    clock: Mock,
    timers: list[Timer],
    removal: str,
    found_at: float,
    fetches: list[float],
) -> None:
    """Fetch for a device that Google removed as for a new one when mDNS finds it again with the same ID.

    It may have been added back, so its next report is a first report. A report
    before the list that drops it arrives neither starts nor delays the fetch.
    """
    network = Network(
        clock, timers, [found("kitchen", "10.0.0.2"), found("office", "10.0.0.3")]
    )
    due = fetches[-1]

    async def run() -> None:
        await network.setup()
        if removal == "while fetching":
            task = await held_fetch(network, 1200)
            network.report("office", "10.0.0.3", at=1201)
            network.listed = [found("kitchen", "10.0.0.2")]
            network.google_answers = True
            await task
        else:
            network.report("office", "10.0.0.3", at=100)
            network.listed = [found("kitchen", "10.0.0.2")]
            if removal == "scheduled":
                await network.update(1200)
            else:
                network.report("tv", "10.0.0.9", at=200)
                await network.fire_due()
                await asyncio.gather(*network.tasks)
        assert network.live() == []
        network.report("office", "10.0.0.7", at=found_at)
        assert network.live() == [due]
        await network.update(due - 1)
        network.listed.append(found("office", None))
        await network.fire_due()
        await asyncio.gather(*network.tasks)
        assert ("office", "10.0.0.7") in network.polled
        network.report("office", "10.0.0.7", at=due + 100)
        assert network.live() == []

    asyncio.run(run())
    assert network.fetches == fetches


def test_removed_device_left_on_network_fetched_for_once(
    clock: Mock, timers: list[Timer]
) -> None:
    """Fetch only once for a device that Google removed and that stays on the network."""
    network = Network(
        clock, timers, [found("kitchen", "10.0.0.2"), found("office", "10.0.0.3")]
    )

    async def run() -> None:
        await network.setup()
        network.report("office", "10.0.0.3", at=100)
        network.listed = [found("kitchen", "10.0.0.2")]
        await network.update(1200)
        network.report("office", "10.0.0.3", at=1300)
        await network.fire_due()
        await asyncio.gather(*network.tasks)
        # Later than 5 minutes after the fetch at 1330
        network.report("office", "10.0.0.3", at=1700)
        assert network.live() == []

    asyncio.run(run())
    assert network.fetches == [0, 1200, 1330]


def test_removed_device_found_while_known_hosts_are_asked(
    clock: Mock, timers: list[Timer]
) -> None:
    """Count a report as after the removal as soon as the client has Google's new list.

    The fetch is still asking the known hosts for a device without an address.
    """
    hosts_answer = [True]

    async def no_answer() -> None:
        await until(lambda: hosts_answer[0])
        raise TimeoutError

    session = MagicMock()
    session.get.return_value.__aenter__.side_effect = no_answer
    listed = [found("kitchen", "10.0.0.2"), found("bedroom", None)]
    network = Network(
        clock, timers, [*listed, found("office", "10.0.0.3")], session, ["10.0.1.9"]
    )

    async def run() -> None:
        await network.setup()
        network.report("office", "10.0.0.3", at=100)
        network.listed = listed
        hosts_answer[0] = False
        asked = session.get.call_count
        task = asyncio.ensure_future(network.update(1200))
        await until(lambda: session.get.call_count > asked)
        network.report("office", "10.0.0.7", at=1201)
        hosts_answer[0] = True
        await task

    asyncio.run(run())
    assert network.live() == [1231]


def test_fetch_due_from_first_device_still_missing(
    clock: Mock, timers: list[Timer]
) -> None:
    """Count the 30 seconds from the first device that the fetch didn't list."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        task = await held_fetch(network, 1200)
        network.report("office", "10.0.0.7", at=1201)
        network.report("bedroom", "10.0.0.8", at=1205)
        network.listed.append(found("office", None))
        network.google_answers = True
        await task

    asyncio.run(run())
    assert network.live() == [1235]


def test_unload_cancels_timer(clock: Mock, timers: list[Timer]) -> None:
    """Cancel the timer for a found device when the entry unloads."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        network.report("office", "10.0.0.7", at=100)
        [timer] = network.timers
        assert timer.at == 130
        network.client.found_devices.async_stop()
        assert timer.cancelled
        assert network.live() == []

    asyncio.run(run())


@pytest.mark.parametrize("unload", [True, False])
def test_unload_while_update_for_found_devices_runs(
    clock: Mock, timers: list[Timer], unload: bool
) -> None:
    """Set no timer once the entry unloads, even when cancelling the update cleans up.

    The update fetched the list and is asking the devices when another device is
    found. Without an unload, it sets the timer for that device when it ends.
    """
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        await network.update(1200)
        network.report("office", "10.0.0.7", at=1201)
        network.devices_answer = False
        await network.fire_due()
        assert network.fetches == [0, 1200, 1231]
        network.report("bedroom", "10.0.0.8", at=1235)
        assert network.live() == []
        [task] = network.tasks
        if unload:
            network.client.found_devices.async_stop()
            with suppress(asyncio.CancelledError):
                await task
            await settle()
            assert network.live() == []
            for timer in list(network.timers):
                await network.fire(timer)
            assert network.requests == 1
            assert network.fetches == [0, 1200, 1231]
        else:
            network.devices_answer = True
            await task
            # Five minutes after the last fetch for found devices started
            assert network.live() == [1531]

    asyncio.run(run())


def test_scheduled_fetch_doesnt_delay(clock: Mock, timers: list[Timer]) -> None:
    """Fetch 30 seconds after mDNS finds a device, however recently the scheduled fetch ran."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        await network.update(1200)
        network.report("office", "10.0.0.7", at=1210)
        await network.fire_due()

    asyncio.run(run())
    assert network.fetches == [0, 1200, 1240]


@pytest.mark.parametrize(
    ("found_at", "due"),
    [
        # Within 5 minutes of the fetch for office at 1240
        (1300, 1540),
        # Later than that: 30 seconds after it was found
        (1600, 1630),
    ],
)
def test_fetches_for_found_devices_5_minutes_apart(
    clock: Mock, timers: list[Timer], found_at: float, due: float
) -> None:
    """Fetch for found devices at most every 5 minutes."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        await network.update(1200)
        network.report("office", "10.0.0.7", at=1210)
        await network.fire_due()
        network.report("bedroom", "10.0.0.8", at=found_at)
        assert network.live() == [due]

    asyncio.run(run())


def test_rejected_token_fetch_doesnt_delay(clock: Mock, timers: list[Timer]) -> None:
    """Fetch 30 seconds after mDNS finds a device, however recently a rejected token caused a fetch.

    The rejection comes before the scheduled fetch at 1200, so only it fetches the list.
    """
    old_token = "token"
    sent: list[str] = []

    def request(
        _method: str, _url: str, *, headers: dict[str, str], **_: object
    ) -> MagicMock:
        sent.append(headers[HEADER_CAST_LOCAL_AUTH])
        response = MagicMock()
        response.__aenter__.return_value.status = (
            HTTPStatus.UNAUTHORIZED if sent[-1] == old_token else HTTPStatus.OK
        )
        response.__aenter__.return_value.json = AsyncMock(
            return_value={"alarm": [], "timer": []}
        )
        return response

    network = Network(
        clock,
        timers,
        [found("kitchen", "10.0.0.2")],
        Mock(request=Mock(side_effect=request)),
    )
    network.real_polling = True

    async def run() -> None:
        await network.setup()
        # Kitchen rejects its old token, and accepts the one Google gives again
        network.device("kitchen").auth_token = old_token
        await network.update(250)
        assert sent == [old_token, LOCAL_AUTH_TOKEN]
        assert network.device("kitchen").auth_token == LOCAL_AUTH_TOKEN
        assert network.fetches == [0, 250]
        network.report("office", "10.0.0.7", at=260)
        assert network.live() == [290]
        await network.fire_due()

    asyncio.run(run())
    assert network.fetches == [0, 250, 290]


def test_scan_replaces_older_mdns_address(clock: Mock, timers: list[Timer]) -> None:
    """Use the address that a fetch's scan finds over one that mDNS reported before the fetch."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        network.report("kitchen", "10.0.0.3", at=100)
        network.listed = [found("kitchen", "10.0.0.4")]
        await network.update(1200)

    asyncio.run(run())
    assert network.polled == [("kitchen", "10.0.0.4")]


def test_mdns_address_during_fetch_replaces_scan(
    clock: Mock, timers: list[Timer]
) -> None:
    """Keep an address that mDNS reports while a fetch runs, rather than the fetch's older scan."""
    network = Network(clock, timers, [found("kitchen", "10.0.0.2")])

    async def run() -> None:
        await network.setup()
        task = await held_fetch(network, 1200)
        network.report("kitchen", "10.0.0.5", at=1201)
        network.google_answers = True
        await task

    asyncio.run(run())
    assert network.polled == [("kitchen", "10.0.0.5")]
