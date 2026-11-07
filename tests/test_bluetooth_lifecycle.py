"""Entity-level persistence and expiry checks inside real Home Assistant setup."""

import json
import logging
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_capture_events

from custom_components.google_home import bluetooth_storage
from custom_components.google_home.bluetooth import BluetoothScanError
from custom_components.google_home.bluetooth_coordinator import BluetoothCoordinator
from custom_components.google_home.bluetooth_storage import async_history, utc_timestamp

# pylint: disable=wrong-import-order
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import test_bluetooth_setup
from .test_bluetooth import IRK, PHONE, heard, rpa, subentry
from .test_bluetooth_reload_shutdown import file_backend
from .test_bluetooth_setup import TRACKER, Scans, scan, track_phone
from .test_coordinators import runtime
from .test_setup import set_up
from .test_unsupported_devices import SPEAKER

# pylint: enable=wrong-import-order

# Pytest discovers this shared fixture by its declared name.
fixture_scans = test_bluetooth_setup.fixture_scans


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("presence", [STATE_HOME, STATE_NOT_HOME])
@pytest.mark.parametrize("new_manager", [False, True], ids=["reload", "fresh-manager"])
async def test_recent_state_is_first_entity_state_after_recreation(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    presence: str,
    new_manager: bool,
) -> None:
    """Restore unused evidence before adding entities, then rebuild live coverage."""
    await track_phone(hass, config_entry)
    if presence == STATE_HOME:
        scans.heard[SPEAKER] = [heard(rpa(IRK))]
    result = STATE_UNKNOWN
    for now in (30, 60, 90):
        result = await scan(hass, config_entry, scans, now)
    assert result == presence
    history = async_history(hass, config_entry)
    saved = history.snapshot()
    changes = async_capture_events(hass, EVENT_STATE_CHANGED)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    if new_manager:
        # New owner loads the real Store, with no memory bindings/coverage.
        hass.data[bluetooth_storage._HISTORY_KEY].pop(config_entry.entry_id)  # noqa: SLF001 # pylint: disable=protected-access
    scans.now = 105
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    states = [
        event.data["new_state"].state
        for event in changes
        if event.data["entity_id"] == TRACKER and event.data["new_state"]
    ]
    assert states[-1] == presence
    assert STATE_UNKNOWN not in states
    restored = async_history(hass, config_entry)
    assert restored.snapshot()["trackers"] == saved["trackers"]
    scanner = runtime(config_entry).bluetooth_scanner
    assert scanner is not None
    assert not any(
        cast(dict[str, object], item)["covers_presence_window"]
        for item in scanner.diagnostics().values()
    )


@pytest.mark.usefixtures("google", "replies")
async def test_timer_expires_entity_without_scan_and_preserves_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
) -> None:
    """Polling cannot keep stale state forever; expiry cannot reset a failed DUC."""

    await track_phone(hass, config_entry)
    for now in (30, 60, 90):
        await scan(hass, config_entry, scans, now)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    scans.errors[SPEAKER] = BluetoothScanError("offline")
    await scan(hass, config_entry, scans, 120)
    coordinator.last_update_success = False
    scans.now = 390
    coordinator._expire()  # noqa: SLF001 # pylint: disable=protected-access
    assert coordinator.last_update_success is False
    state = hass.states.get(TRACKER)
    assert state is not None and state.state == "unavailable"
    assert coordinator.data is not None
    assert coordinator.data[PHONE].state == "unavailable"
    # A stale callback after unload neither publishes nor resurrects evidence.
    await hass.config_entries.async_unload(config_entry.entry_id)
    scans.now = 391
    coordinator._expire()  # noqa: SLF001 # pylint: disable=protected-access


@pytest.mark.usefixtures("google", "replies")
async def test_detected_clock_jump_drops_old_evidence(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
) -> None:
    """A detected clock discontinuity starts fresh without retaining old coverage."""
    await track_phone(hass, config_entry)
    for now in (30, 60, 90):
        await scan(hass, config_entry, scans, now)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)

    wall = utc_timestamp()
    with patch(
        "custom_components.google_home.bluetooth_storage.utc_timestamp",
        return_value=wall + 10,
    ):
        coordinator._expire()  # noqa: SLF001 # pylint: disable=protected-access
    assert coordinator.data[PHONE].state == "unknown"
    assert not coordinator.history.sources and not coordinator.history.trackers


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("presence", [STATE_HOME, STATE_NOT_HOME])
async def test_real_coordinator_failure_closes_reload_eligibility(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    presence: str,
) -> None:
    """Unexpected DUC failure, rather than a handled scan miss, cannot restore home/away."""
    await track_phone(hass, config_entry)
    if presence == STATE_HOME:
        scans.heard[SPEAKER] = [heard(rpa(IRK))]
    for now in (30, 60, 90):
        await scan(hass, config_entry, scans, now)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    original_c = coordinator.scanner.tracked[0].confirmed_at
    original_leases = [
        (row.last_success, row.deadline) for row in coordinator.history.sources.values()
    ]
    scans.now = 105
    with patch.object(
        coordinator.scanner,
        "async_update",
        side_effect=RuntimeError("unexpected scanner error"),
    ):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    failed_state = hass.states.get(TRACKER)
    assert failed_state is not None and failed_state.state == "unavailable"
    assert not coordinator.history.trackers
    assert coordinator.scanner.tracked[0].confirmed_at == original_c
    assert [
        (row.last_success, row.deadline) for row in coordinator.history.sources.values()
    ] == original_leases
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(TRACKER)
    assert state is not None and state.state == "unknown"


def saved_home(wall: float) -> dict[str, object]:
    """Return a tracker row, as snapshot() saves it, that restores home at wall."""
    return {
        "revision": "invented-config-revision",
        "state": STATE_HOME,
        "sighted": wall - 10,
        "confirmed": wall - 10,
        "expires": wall + 290,
    }


def saved_file(hass: HomeAssistant, entry: MockConfigEntry, tmp_path: Path) -> Path:
    """Track the phone and the tablet, and read this entry's saved state from a real file.

    The file goes through Home Assistant's own file reading and Store envelope handling.
    """
    hass.config_entries.async_update_entry(entry, options={"bluetooth_tracking": True})
    hass.config_entries.async_add_subentry(entry, subentry({"irk": IRK.hex()}))
    hass.config_entries.async_add_subentry(
        entry, subentry({"mac": "AA:BB:CC:DD:EE:FF"}, "tablet", "Tablet")
    )
    history = async_history(hass, entry)
    path = tmp_path / history._store.key  # noqa: SLF001 # pylint: disable=protected-access
    file_backend(history, str(path))
    return path


def assert_loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Check that the entry is set up with its speaker's ordinary entities."""
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.kitchen_speaker_device") is not None


def tracker_state(hass: HomeAssistant, entity_id: str) -> str:
    """Return a tracker's state, which must exist."""
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


@pytest.mark.usefixtures("google", "replies", "scans", "freezer")
@pytest.mark.parametrize(
    "saved",
    [
        "newer version",
        "unreadable",
        "corrupt and can't be moved aside",
        "not an object",
        "no version",
        "older version",
    ],
)
async def test_saved_state_that_cannot_load_is_skipped(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    saved: str,
) -> None:
    """Setup goes on without a saved file Home Assistant's Store can't load."""
    path = saved_file(hass, config_entry, tmp_path)
    data = {
        "policy": 1,
        "trackers": {PHONE: saved_home(bluetooth_storage.utc_timestamp())},
    }
    if saved == "unreadable":
        # Reading it fails as reading a file without permission does
        path.mkdir()
    elif saved == "corrupt and can't be moved aside":
        # Store renames a corrupt file to this name, which a directory takes
        path.write_text("{")
        Path(f"{path}.corrupt.{dt_util.utcnow().isoformat()}").mkdir()
    else:
        path.write_text(
            json.dumps(
                {
                    "newer version": {"version": 2, "minor_version": 1, "data": data},
                    "not an object": [],
                    "no version": {"data": data},
                    "older version": {"version": 0, "data": data},
                }[saved]
            )
        )
    await set_up(hass, config_entry)
    assert_loaded(hass, config_entry)
    assert tracker_state(hass, TRACKER) == STATE_UNKNOWN
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == bluetooth_storage.__name__
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert path.name in warnings[0]


@pytest.mark.usefixtures("google", "replies", "scans")
@pytest.mark.parametrize("state", [[], {}], ids=["list", "object"])
async def test_malformed_saved_tracker_is_skipped_alone(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    tmp_path: Path,
    state: object,
) -> None:
    """A saved tracker with a state that isn't text doesn't stop the others restoring."""
    path = saved_file(hass, config_entry, tmp_path)
    wall = bluetooth_storage.utc_timestamp()
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "minor_version": 1,
                "data": {
                    "policy": 1,
                    "trackers": {
                        PHONE: {**saved_home(wall), "state": state},
                        "tablet": saved_home(wall),
                    },
                },
            }
        )
    )
    await set_up(hass, config_entry)
    assert_loaded(hass, config_entry)
    assert tracker_state(hass, TRACKER) == STATE_UNKNOWN
    assert tracker_state(hass, "device_tracker.tablet") == STATE_HOME
