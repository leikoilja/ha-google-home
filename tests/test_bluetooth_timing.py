"""Tests for Bluetooth scans when the speakers take time to answer.

The fake speakers take time to answer each request, and each update starts when Home
Assistant would start it.
"""

import asyncio
import math
from typing import override

from aiohttp import ClientTimeout
import pytest

from custom_components.google_home.bluetooth import (
    BluetoothScanError,
    BluetoothScanner,
    TrackerState,
    TrackerUpdate,
    async_get_bluetooth_scan_results,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

from .test_bluetooth import (
    HOME,
    IRK,
    NOT_HOME,
    PHONE,
    Speakers,
    faked,
    heard,
    make_scanner,
    rpa,
)
from .test_bluetooth_requests import KITCHEN, mock_session


class SlowSpeakers(Speakers):
    """Fake speakers that take time to answer, in updates timed as Home Assistant does.

    Speakers are asked at the same time: while one answers, the scanner reads that
    speaker's time, and after them, the time the slowest one finished. The next update
    starts at the whole second that one ended, plus the interval and half a second, the
    most Home Assistant adds.
    """

    def __init__(self, *names: str) -> None:
        """Create speakers that answer at once, with the timeout their requests have."""
        super().__init__(*names)
        # Start of the next update
        self.start = 1000.5
        # How long each speaker takes to answer its results and scan requests in the
        # next update, by device ID; None never answers
        self.delays: dict[str, tuple[float | None, float | None]] = {}
        self._elapsed: dict[asyncio.Task[object] | None, float] = {}
        self._update: asyncio.Task[object] | None = None
        session = mock_session(body=[])
        asyncio.run(async_get_bluetooth_scan_results(session, KITCHEN))
        self._timeout: ClientTimeout = session.request.call_args.kwargs["timeout"]

    def longest_wait(self, sent: float) -> float:
        """Return how long a request sent at this time waits for an answer.

        aiohttp rounds a timeout of ceil_threshold seconds or more up to its clock's
        next whole second.
        """
        total = self._timeout.total
        assert total is not None
        deadline = sent + total
        if total >= self._timeout.ceil_threshold:
            deadline = math.ceil(deadline)
        return deadline - sent

    def monotonic(self) -> float:
        """Return the time the scanner reads."""
        task = asyncio.current_task()
        if task is self._update:
            return self.start + max(self._elapsed.values(), default=0.0)
        return self.start + self._elapsed.get(task, 0.0)

    def _answer(self, delay: float | None) -> None:
        """Take the time the speaker answering a request takes, or time out."""
        task = asyncio.current_task()
        sent = self._elapsed.get(task, 0.0)
        wait = self.longest_wait(self.start + sent)
        if delay is None or delay >= wait:
            self._elapsed[task] = sent + wait
            raise BluetoothScanError("timeout")
        self._elapsed[task] = sent + delay

    @override
    async def async_get_bluetooth_scan_results(
        self, _session: object, device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        """Return what the speaker heard, once it answers."""
        self._answer(self.delays.get(device.device_id, (0.0, 0.0))[0])
        return await super().async_get_bluetooth_scan_results(_session, device)

    @override
    async def async_start_bluetooth_scan(
        self, _session: object, device: GoogleHomeDevice
    ) -> None:
        """Start a scan, once the speaker answers."""
        self._answer(self.delays.get(device.device_id, (0.0, 0.0))[1])
        await super().async_start_bluetooth_scan(_session, device)

    def update(self, scanner: BluetoothScanner) -> TrackerState:
        """Run the next update and return the phone's state."""

        async def refresh() -> TrackerUpdate:
            self._update = asyncio.current_task()
            return (await scanner.async_update())[PHONE]

        self._elapsed = {}
        with faked(self, self.monotonic):
            state = asyncio.run(refresh()).state
        end = self.start + max(self._elapsed.values(), default=0.0)
        self.start = int(end) + 30.5
        return state


@pytest.mark.parametrize("silent", [["office"], ["office", "bedroom"]])
def test_scan_read_within_timeout_after_slow_update(silent: list[str]) -> None:
    """Use a scan whose results arrive just within the timeout, after a slow update.

    The update that started the scan waited for the speakers that answered neither
    request. A speaker's own answer and that wait must fit in the time its results
    stay usable. Speakers are asked at the same time, so several that don't answer
    cost as much as one.
    """
    speakers = SlowSpeakers("Kitchen", "Bedroom", "Office")
    scanner = make_scanner(speakers)
    assert [speakers.update(scanner) for _ in range(4)][-1] == NOT_HOME

    speakers.delays = dict.fromkeys(silent, (None, None))
    assert speakers.update(scanner) == NOT_HOME
    # The phone arrived during the kitchen's scan
    speakers.results["kitchen"] = [heard(rpa(IRK))]
    speakers.delays["kitchen"] = (speakers.longest_wait(speakers.start) - 0.01, 0.0)
    assert speakers.update(scanner) == HOME


@pytest.mark.parametrize(("bedroom", "state"), [(1.0, HOME), (1.01, NOT_HOME)])
def test_scan_age_counted_to_its_results(bedroom: float, state: TrackerState) -> None:
    """Count a scan's age to when its own speaker's results arrive.

    Home Assistant runs the update 44 seconds after the last, as when it's busy. The
    bedroom heard the phone, and its scan is used up to 45 seconds after it started,
    though the kitchen answers later.
    """
    speakers = SlowSpeakers("Kitchen", "Bedroom")
    scanner = make_scanner(speakers)
    for _ in range(3):
        speakers.update(scanner)
    started = speakers.start
    assert speakers.update(scanner) == NOT_HOME

    speakers.results["bedroom"] = [heard(rpa(IRK))]
    speakers.start = started + 44
    speakers.delays = {"kitchen": (2.0, 0.0), "bedroom": (bedroom, 0.0)}
    assert speakers.update(scanner) == state
