"""Invented original-sighting timelines for optional covered departure delay."""

# These tests inspect pending tokens and original ages to detect false renewal.
# ruff: noqa: SLF001

import asyncio
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.bluetooth import (
    BluetoothScanError,
    BluetoothScanner,
    DepartureToken,
)
from custom_components.google_home.bluetooth_coordinator import BluetoothCoordinator
from custom_components.google_home.bluetooth_storage import (
    BluetoothHistory,
    SourceEvidence,
    async_history,
)

# pylint: disable=wrong-import-order,protected-access
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import test_bluetooth_setup, test_bluetooth_storage
from .test_bluetooth import IRK, PHONE, Speakers, heard, rpa, subentry
from .test_bluetooth_setup import TRACKER, Scans, scan, track_phone
from .test_bluetooth_storage import WALL, scanner_for
from .test_coordinators import runtime
from .test_unsupported_devices import SPEAKER

# pylint: enable=wrong-import-order

fixture_evidence = test_bluetooth_storage.fixture_evidence
fixture_scans = test_bluetooth_setup.fixture_scans


def pending_home(
    history: BluetoothHistory, now: list[float], delay: int | None
) -> BluetoothScanner:
    """A known HOME at C=30/S=0 meets actual negative evidence at t=90."""
    tracked_subentry = history.entry.subentries[PHONE]
    if delay is not None:
        history.hass.config_entries.async_update_subentry(
            history.entry,
            tracked_subentry,
            data=dict(tracked_subentry.data) | {"additional_departure_delay": delay},
        )
    now[0] = 30
    history.confirm(PHONE, "home", 0, 30, "live", WALL)
    scanner = scanner_for(history, Speakers("A"))
    scanner._update_speakers()
    a = scanner._speakers["a"]
    a.run_start, a.covered_until = 0, 60
    now[0] = 90
    scanner._read_scan("a", a, 60, [])
    return scanner


def token_for(scanner: BluetoothScanner) -> DepartureToken:
    """Read the current pending token after a mutating runtime operation."""
    token = scanner.tracked[0].pending_departure
    assert token is not None
    return token


def negative(scanner: BluetoothScanner, now: list[float], time: float) -> None:
    """Accept a new owned empty interval, without manufacturing a positive."""
    now[0] = time
    scanner._read_scan("a", scanner._speakers["a"], time - 30, [])


@pytest.mark.parametrize("delay", [None, 0, 30, 60, 90, 120])
async def test_original_departure_threshold(
    evidence: tuple[BluetoothHistory, list[float]], delay: int | None
) -> None:
    """Missing/zero uses90; nonzero postpones only the known-home transition."""
    history, now = evidence
    scanner = pending_home(history, now, delay)
    first = scanner.evaluate(scan=True)[PHONE].state
    if not delay:
        assert first == "not_home"
        assert history.trackers[PHONE].confirmed == 90
        return
    assert first == "home"
    assert history.trackers[PHONE].confirmed == 30
    token = scanner.tracked[0].pending_departure
    assert token is not None and token.deadline == 90 + delay
    for time in range(120, 90 + delay, 30):
        negative(scanner, now, time)
        assert scanner.evaluate(scan=True)[PHONE].state == "home"
        assert scanner.tracked[0].pending_departure == token
    now[0] = 90 + delay - 0.01
    assert scanner.evaluate()[PHONE].state == "home"
    negative(scanner, now, 90 + delay)
    assert scanner.evaluate(scan=True)[PHONE].state == "not_home"
    assert (history.trackers[PHONE].confirmed, history.trackers[PHONE].expires) == (
        90 + delay,
        390 + delay,
    )


@pytest.mark.parametrize("return_at", [120, 150])
async def test_positive_cancels_short_pulse(
    evidence: tuple[BluetoothHistory, list[float]], return_at: int
) -> None:
    """A return before original S+180 suppresses the synthetic away pulse."""
    history, now = evidence
    scanner = pending_home(history, now, 90)
    assert scanner.evaluate(scan=True)[PHONE].state == "home"
    token = scanner.tracked[0].pending_departure
    if return_at == 150:
        negative(scanner, now, 120)
        assert scanner.evaluate(scan=True)[PHONE].state == "home"
    now[0] = return_at
    scanner._read_scan(
        "a", scanner._speakers["a"], return_at - 30, [heard("AA:BB:CC:DD:EE:FF")]
    )
    assert scanner.tracked[0].pending_departure is None
    assert scanner.evaluate(scan=True)[PHONE].state == "home"
    confirmed = history.trackers[PHONE].confirmed
    now[0] = 180
    assert token is not None
    assert scanner.evaluate(departures={PHONE: token})[PHONE].state == "home"
    assert history.trackers[PHONE].confirmed == confirmed


@pytest.mark.parametrize("callback", [150, 166])
async def test_callback_actual_time_and_consumption(
    evidence: tuple[BluetoothHistory, list[float]], callback: int
) -> None:
    """No scan at the callback: actual coverage decides, and token is single-use."""
    history, now = evidence
    scanner = pending_home(history, now, 60)
    assert scanner.evaluate(scan=True)[PHONE].state == "home"
    negative(scanner, now, 120)
    assert scanner.evaluate(scan=True)[PHONE].state == "home"
    token = scanner.tracked[0].pending_departure
    assert token is not None
    row = next(iter(history.sources.values()))
    assert (row.last_success, row.deadline) == (120, 420)
    now[0] = callback
    assert scanner.evaluate(departures={PHONE: token})[PHONE].state == (
        "not_home" if callback == 150 else "home"
    )
    confirmed = 150 if callback == 150 else 30
    assert (history.trackers[PHONE].confirmed, history.trackers[PHONE].expires) == (
        confirmed,
        confirmed + 300,
    )
    assert history.trackers[PHONE].sighted == 0
    assert (row.last_success, row.deadline) == (120, 420)
    now[0] += 1
    scanner.evaluate(departures={PHONE: token})
    assert history.trackers[PHONE].confirmed == confirmed
    if callback == 166:
        now[0] = 330
        assert scanner.evaluate()[PHONE].state == "unavailable"


@pytest.mark.parametrize("failure", ["coverage", "zero", "unbound", "health"])
async def test_pending_callback_needs_current_evidence(
    evidence: tuple[BluetoothHistory, list[float]], failure: str
) -> None:
    """A pending deadline grants no absence or new confirmation by itself."""
    history, now = evidence
    scanner = pending_home(history, now, 60)
    scanner.evaluate(scan=True)
    negative(scanner, now, 120)
    scanner.evaluate(scan=True)
    token = scanner.tracked[0].pending_departure
    assert token is not None
    if failure == "coverage":
        scanner._speakers["a"].run_start = None
    elif failure == "zero":
        history.sources.clear()
    elif failure == "unbound":
        history.sources["missing"] = SourceEvidence(
            "missing", None, 120, 420, WALL + 120, WALL + 420
        )
    now[0] = 150
    assert (
        scanner.evaluate(healthy=failure != "health", departures={PHONE: token})[
            PHONE
        ].state
        == "home"
    )
    assert history.trackers[PHONE].confirmed == 30
    assert scanner.tracked[0].pending_departure is None
    now[0] = 330
    assert scanner.evaluate()[PHONE].state == "unavailable"


@pytest.mark.parametrize(
    ("new_delay", "edit_at", "deadline"), [(120, 120, 210), (30, 160, 120)]
)
async def test_edit_pending_keeps_evidence_and_replaces_only_token(
    evidence: tuple[BluetoothHistory, list[float]],
    new_delay: int,
    edit_at: int,
    deadline: int,
) -> None:
    """Policy changes retain S/C/E/L/D; old and same-value callbacks stay distinct."""
    history, now = evidence
    scanner = pending_home(history, now, 60)
    scanner.evaluate(scan=True)
    device = scanner.tracked[0]
    old = device.pending_departure
    assert old is not None
    snapshot = history.snapshot()
    generation = history.generation
    now[0] = edit_at
    with (
        patch.object(history, "schedule_save") as save,
        patch.object(history, "confirm") as confirm,
    ):
        history.hass.config_entries.async_update_subentry(
            history.entry,
            history.entry.subentries[PHONE],
            data=dict(history.entry.subentries[PHONE].data)
            | {"additional_departure_delay": new_delay},
        )
        assert scanner.sync_departure_delays()
        assert history.snapshot() == snapshot
        assert history.generation == generation
        save.assert_not_called()
        confirm.assert_not_called()
    token = device.pending_departure
    assert token is not None and token != old and token.deadline == deadline
    assert not scanner.sync_departure_delays()
    assert device.pending_departure is token
    scanner.evaluate(departures={PHONE: old})
    assert history.trackers[PHONE].confirmed == 30


async def test_cold_and_previous_away_have_no_home_grace(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """A delay setting cannot manufacture HOME from cold or previously-away state."""
    history, now = evidence
    history.hass.config_entries.async_update_subentry(
        history.entry,
        history.entry.subentries[PHONE],
        data=dict(history.entry.subentries[PHONE].data)
        | {"additional_departure_delay": 120},
    )
    scanner = scanner_for(history, Speakers("A"))
    scanner._update_speakers()
    scanner._speakers["a"].run_start = 0
    scanner._speakers["a"].covered_until = 60
    negative(scanner, now, 90)
    device = scanner.tracked[0]
    assert scanner.evaluate(scan=True)[PHONE].state == "not_home"
    assert device.pending_departure is None
    now[0] = 120
    negative(scanner, now, 120)
    assert scanner.evaluate(scan=True)[PHONE].state == "not_home"
    assert history.trackers[PHONE].confirmed == 120


@pytest.mark.parametrize("fresh_manager", [False, True])
async def test_reload_preserves_marked_pre_grace_evidence(
    evidence: tuple[BluetoothHistory, list[float]],
    fresh_manager: bool,
) -> None:
    """Reconfigure metadata does not rewrite a marked v1 row or restart its threshold."""
    history, now = evidence
    pending_home(history, now, None)
    snapshot = history.snapshot()
    await history.async_flush()
    history.hass.config_entries.async_update_subentry(
        history.entry,
        history.entry.subentries[PHONE],
        data=dict(history.entry.subentries[PHONE].data)
        | {"additional_departure_delay": 120},
    )
    now[0] = 100
    owner = history
    if fresh_manager:
        owner = BluetoothHistory(history.hass, history.entry)
        await owner.async_load(lambda: now[0])
    restored = scanner_for(owner, Speakers("A"))
    assert restored.evaluate()[PHONE].state == "home"
    assert owner.snapshot()["trackers"] == snapshot["trackers"]
    assert restored.tracked[0].pending_departure is None
    a = restored._speakers["a"]
    a.run_start, a.covered_until = 100, 160
    now[0] = 190
    restored._read_scan("a", a, 160, [])
    assert restored.evaluate(scan=True)[PHONE].state == "home"
    token = token_for(restored)
    assert token.deadline == 210
    if fresh_manager:
        await owner.async_flush()


@pytest.mark.usefixtures("google", "replies")
async def test_real_reconfigure_is_inline_isolated_and_does_not_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    entity_registry: er.EntityRegistry,
) -> None:
    """HA's one listener changes only one runtime token, even before its task runs."""
    await track_phone(hass, config_entry)
    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    assert await scan(hass, config_entry, scans, 30) == "home"
    scans.heard[SPEAKER] = []
    await reconfigure_delay(hass, config_entry, 60)
    assert await scan(hass, config_entry, scans, 60) == "home"
    assert await scan(hass, config_entry, scans, 90) == "home"
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    scanner = coordinator.scanner
    device = scanner.tracked[0]
    token = device.pending_departure
    assert token is not None and token.deadline == 150
    registered = entity_registry.async_get(TRACKER)
    assert registered is not None
    history = async_history(hass, config_entry)
    snapshot = history.snapshot()
    generation = history.generation
    instance = scanner._instance
    assert history.owns_scanner(instance)
    requests = list(scans.started)
    with (
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
        patch.object(history, "schedule_save") as save,
    ):
        await reconfigure_delay(hass, config_entry, 120)
        changed = device.pending_departure
        assert changed is not None and changed.deadline == 210
        assert changed != token
        await reconfigure_delay(hass, config_entry, 120)
        assert device.pending_departure is changed
        # HA calls the registered wrapper inline: intermediate values are seen
        # even with no event-loop yield between these updates.
        for delay in (60, 120):
            hass.config_entries.async_update_subentry(
                config_entry,
                config_entry.subentries[PHONE],
                data=dict(config_entry.subentries[PHONE].data)
                | {"additional_departure_delay": delay},
            )
        current = token_for(scanner)
        assert current != changed
        assert current.policy_generation == changed.policy_generation + 2
        coordinator._depart(PHONE, token, scanner.generation)
        assert history.snapshot() == snapshot
        assert history.generation == generation
        assert scanner._instance is instance and history.owns_scanner(instance)
        await hass.async_block_till_done()
        reload.assert_not_called()
        save.assert_not_called()
    assert runtime(config_entry).bluetooth is coordinator
    assert runtime(config_entry).bluetooth_scanner is scanner
    assert entity_registry.async_get(TRACKER) is registered
    assert device.identity == (IRK.hex(), None)
    assert scans.started == requests
    assert hass.states.is_state(TRACKER, "home")


@pytest.mark.usefixtures("google", "replies")
async def test_real_callback_early_duplicate_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, scans: Scans
) -> None:
    """A queued callback owns one actual-time decision and cannot survive unload."""
    await track_phone(hass, config_entry)
    await reconfigure_delay(hass, config_entry, 60)
    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    await scan(hass, config_entry, scans, 30)
    scans.heard[SPEAKER] = []
    for time in (60, 90, 120):
        await scan(hass, config_entry, scans, time)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    scanner = coordinator.scanner
    token = token_for(scanner)
    requests = list(scans.started)
    scans.now = 149.99
    coordinator._depart(PHONE, token, scanner.generation)
    assert hass.states.is_state(TRACKER, "home")
    scans.now = 150
    coordinator._depart(PHONE, token, scanner.generation)
    assert hass.states.is_state(TRACKER, "not_home")
    history = coordinator.history
    assert (history.trackers[PHONE].confirmed, history.trackers[PHONE].expires) == (
        150,
        450,
    )
    scans.now = 151
    coordinator._depart(PHONE, token, scanner.generation)
    assert history.trackers[PHONE].confirmed == 150
    await hass.config_entries.async_unload(config_entry.entry_id)
    scans.now = 152
    coordinator._depart(PHONE, token, scanner.generation)
    assert history.trackers[PHONE].confirmed == 150
    assert scans.started == requests


async def reconfigure_delay(
    hass: HomeAssistant, entry: MockConfigEntry, delay: int
) -> None:
    """Exercise the actual HA subentry flow and existing listener path."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "bluetooth_device"),
        context={"source": "reconfigure", "subentry_id": PHONE},
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"additional_departure_delay": str(delay)}
    )
    await hass.async_block_till_done()


async def test_membership_expiry_cannot_bypass_delay(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """A legitimate expiry can arm the delay but not jump past original S+180."""
    history, now = evidence
    scanner = pending_home(history, now, 90)
    history.sources["b"] = SourceEvidence("b", "b", -180, 120, WALL - 180, WALL + 120)
    assert scanner.evaluate(scan=True)[PHONE].state == "home"
    assert scanner.tracked[0].pending_departure is None
    now[0] = 120
    assert scanner.evaluate()[PHONE].state == "home"
    token = token_for(scanner)
    assert token.deadline == 180
    assert history.trackers[PHONE].confirmed == 30
    negative(scanner, now, 120)
    scanner.evaluate(scan=True)
    negative(scanner, now, 150)
    scanner.evaluate(scan=True)
    now[0] = 180
    assert scanner.evaluate(departures={PHONE: token})[PHONE].state == "not_home"
    assert history.trackers[PHONE].confirmed == 180


async def test_per_tracker_policy_and_home_arrival(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """The same negative scans can leave a delayed tracker home and another away."""
    history, now = evidence
    history.hass.config_entries.async_add_subentry(
        history.entry, subentry({"mac": "AA:BB:CC:DD:EE:01"}, "second", "Second")
    )
    history.hass.config_entries.async_update_subentry(
        history.entry,
        history.entry.subentries[PHONE],
        data=dict(history.entry.subentries[PHONE].data)
        | {"additional_departure_delay": 60},
    )
    # Both have an invented valid prior HOME confirmation at S=0/C=30.
    now[0] = 30
    history.confirm(PHONE, "home", 0, 30, "live", WALL)
    history.confirm("second", "home", 0, 30, "live", WALL)
    scanner = scanner_for(history, Speakers("A"))
    scanner._update_speakers()
    scanner._speakers["a"].run_start = 0
    scanner._speakers["a"].covered_until = 60
    negative(scanner, now, 90)
    states = scanner.evaluate(scan=True)
    assert states[PHONE].state == "home"
    assert states["second"].state == "not_home"
    other = scanner.tracked[1]
    before = (other.policy_generation, other.pending_departure, other.confirmed_at)
    history.hass.config_entries.async_update_subentry(
        history.entry,
        history.entry.subentries[PHONE],
        data=dict(history.entry.subentries[PHONE].data)
        | {"additional_departure_delay": 120},
    )
    assert scanner.sync_departure_delays()
    assert (
        other.policy_generation,
        other.pending_departure,
        other.confirmed_at,
    ) == before
    now[0] = 120
    scanner._read_scan("a", scanner._speakers["a"], 90, [heard("AA:BB:CC:DD:EE:01")])
    assert scanner.evaluate(scan=True)["second"].state == "home"
    assert other.last_sighted == 90 and other.confirmed_at == 120


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize(
    "failure", ["coordinator", "polling", "tracking", "zero", "request"]
)
async def test_real_due_callback_preserves_failure_and_control_boundaries(
    hass: HomeAssistant, config_entry: MockConfigEntry, scans: Scans, failure: str
) -> None:
    """A due callback cannot hide coordinator failure, disablement or source loss."""
    await track_phone(hass, config_entry)
    await reconfigure_delay(hass, config_entry, 60)
    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    await scan(hass, config_entry, scans, 30)
    scans.heard[SPEAKER] = []
    for time in (60, 90, 120):
        await scan(hass, config_entry, scans, time)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    scanner = coordinator.scanner
    device = scanner.tracked[0]
    token = token_for(scanner)
    original_c = device.confirmed_at
    requests = list(scans.started)
    history = coordinator.history
    with patch.object(hass.config_entries, "async_schedule_reload"):
        if failure == "coordinator":
            coordinator.last_update_success = False
        elif failure == "polling":
            hass.config_entries.async_update_entry(
                config_entry, pref_disable_polling=True
            )
        elif failure == "tracking":
            hass.config_entries.async_update_entry(
                config_entry, options={"bluetooth_tracking": False}
            )
        elif failure == "request":
            scans.errors[SPEAKER] = BluetoothScanError("offline")
            await scan(hass, config_entry, scans, 150)
        else:
            history.sources.clear()
        scans.now = 150
        coordinator._depart(PHONE, token, scanner.generation)
        assert device.confirmed_at == original_c
        assert scans.started == requests
        if failure == "coordinator":
            assert not coordinator.last_update_success
            assert hass.states.is_state(TRACKER, "unavailable")
    await hass.async_block_till_done()


@pytest.mark.usefixtures("google", "replies")
async def test_change_during_inflight_scan_uses_current_policy(
    hass: HomeAssistant, config_entry: MockConfigEntry, scans: Scans
) -> None:
    """A scan keeps its owned evidence but cannot decide using a saved old G."""
    await track_phone(hass, config_entry)
    await reconfigure_delay(hass, config_entry, 60)
    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    await scan(hass, config_entry, scans, 30)
    scans.heard[SPEAKER] = []
    for time in (60, 90, 120):
        await scan(hass, config_entry, scans, time)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    entered, release = asyncio.Event(), asyncio.Event()

    async def results(_session: object, _device: object) -> list[dict[str, object]]:
        entered.set()
        await release.wait()
        return []

    scans.now = 150
    with patch(
        "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
        results,
    ):
        refresh = asyncio.create_task(coordinator.async_refresh())
        await entered.wait()
        hass.config_entries.async_update_subentry(
            config_entry,
            config_entry.subentries[PHONE],
            data=dict(config_entry.subentries[PHONE].data)
            | {"additional_departure_delay": 120},
        )
        release.set()
        await refresh
    await hass.async_block_till_done()
    assert hass.states.is_state(TRACKER, "home")
    assert token_for(coordinator.scanner).deadline == 210
    assert coordinator.history.trackers[PHONE].confirmed == 60


@pytest.mark.usefixtures("google", "replies")
async def test_lower_pending_delay_confirms_at_actual_callback_time(
    hass: HomeAssistant, config_entry: MockConfigEntry, scans: Scans
) -> None:
    """A shorter already-due threshold rechecks live coverage on the next turn."""
    await track_phone(hass, config_entry)
    await reconfigure_delay(hass, config_entry, 120)
    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    await scan(hass, config_entry, scans, 30)
    scans.heard[SPEAKER] = []
    for time in (60, 90, 120):
        await scan(hass, config_entry, scans, time)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    assert token_for(coordinator.scanner).deadline == 210
    scans.now = 160
    requests = list(scans.started)
    await reconfigure_delay(hass, config_entry, 30)
    await asyncio.sleep(0)
    await hass.async_block_till_done()
    assert hass.states.is_state(TRACKER, "not_home")
    assert (
        coordinator.history.trackers[PHONE].confirmed,
        coordinator.history.trackers[PHONE].expires,
    ) == (160, 460)
    assert coordinator.history.trackers[PHONE].sighted == 0
    assert scans.started == requests


async def test_pending_callback_cannot_outlive_same_generation_setup(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """A replacement setup invalidates old delay work independently of policy epochs."""
    history, now = evidence
    old = pending_home(history, now, 60)
    assert old.evaluate(scan=True)[PHONE].state == "home"
    token = token_for(old)
    instance, generation = old._instance, history.generation
    original = history.snapshot()
    current = scanner_for(history, Speakers("A"))
    assert current.current() and not old.current()
    assert current._instance is not instance
    assert history.generation == generation
    history.hass.config_entries.async_update_subentry(
        history.entry,
        history.entry.subentries[PHONE],
        data=dict(history.entry.subentries[PHONE].data)
        | {"additional_departure_delay": 120},
    )
    now[0] = 150
    assert old.evaluate(departures={PHONE: token})[PHONE].state == "home"
    assert old.tracked[0].pending_departure is token
    assert old.tracked[0].departure_delay == 60
    assert history.snapshot() == original
    old.retire()
    assert current.current()
    assert current.sync_departure_delays()
    assert current.tracked[0].departure_delay == 120
    assert history.snapshot() == original
