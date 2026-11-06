"""Regressions for reload ownership, obsolete updates and real HA shutdown."""

# Controlled lifecycle and executor fixtures inspect the single I/O owner.
# ruff: noqa: SLF001

import asyncio
import json
from pathlib import Path
from threading import Event as ThreadEvent
from typing import cast
from unittest.mock import patch

import pytest
from pytest_homeassistant.common import MockConfigEntry, async_capture_events

from custom_components.google_home.bluetooth import (
    BluetoothScanError,
    BluetoothScanUnsupported,
)
from custom_components.google_home.bluetooth_coordinator import BluetoothCoordinator
from custom_components.google_home.bluetooth_storage import BluetoothHistory
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# pylint: disable=wrong-import-order,protected-access
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, storage

from . import test_bluetooth_setup, test_bluetooth_storage
from .test_bluetooth import IRK, PHONE, heard, rpa
from .test_bluetooth_setup import TRACKER, Scans, scan, track_phone
from .test_bluetooth_storage import WALL
from .test_coordinators import runtime

# pylint: enable=wrong-import-order

fixture_scans = test_bluetooth_setup.fixture_scans
fixture_evidence = test_bluetooth_storage.fixture_evidence


def file_backend(history: BluetoothHistory, path: str) -> storage._FileStoreIO:
    """Use the production file backend for this entry, bypassing fixture memory I/O."""
    # The standard hass fixture replaces file I/O with MockStoreIO. Its pinned
    # production base performs real executor I/O in the fixture's temporary dir.
    backend = cast(type[storage._FileStoreIO], type(history._store._io).__mro__[1])
    io = backend(history.hass, history._store.key, path, True, True)
    history._store._io = io
    return io


async def load_file_history(history: BluetoothHistory, now: float) -> BluetoothHistory:
    """Load an independent owner from the actual final file, never pending memory."""
    loaded = BluetoothHistory(history.hass, history.entry)
    file_backend(loaded, history._store._io.path)
    await loaded.async_load(lambda: now)
    return loaded


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize(
    "completion", ["positive", "error", "unsupported", "unexpected"]
)
async def test_manual_refresh_across_ordinary_reload_cannot_mutate_new_instance(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    completion: str,
) -> None:
    """ASTRA-R1-01: an unloaded manual caller never regains shared ownership."""
    await track_phone(hass, config_entry)
    for now in (30, 60, 90):
        await scan(hass, config_entry, scans, now)
    old = runtime(config_entry).bluetooth
    assert isinstance(old, BluetoothCoordinator)
    original = old.history.snapshot()
    old_device = next(iter(runtime(config_entry).account.data.values()))
    entered, release, new_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    old_starts: list[str] = []

    async def held_read(
        _session: object, device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        assert device is old_device
        entered.set()
        await release.wait()
        if completion == "error":
            raise BluetoothScanError("old request failed")
        if completion == "unsupported":
            raise BluetoothScanUnsupported("old endpoint returned 404")
        if completion == "unexpected":
            raise RuntimeError("old request failed unexpectedly")
        return [heard(rpa(IRK))]

    async def start(session: object, device: GoogleHomeDevice) -> None:
        if device is old_device:
            old_starts.append(device.device_id)
        else:
            new_started.set()
        await scans.start(session, device)

    changes = async_capture_events(hass, EVENT_STATE_CHANGED)
    with (
        patch(
            "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
            held_read,
        ),
        patch(
            "custom_components.google_home.bluetooth.async_start_bluetooth_scan", start
        ),
    ):
        scans.now = 120
        manual = asyncio.create_task(old.async_request_refresh())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert await hass.config_entries.async_reload(config_entry.entry_id)
            await asyncio.wait_for(new_started.wait(), 5)
            current = runtime(config_entry).bluetooth
            assert isinstance(current, BluetoothCoordinator) and current is not old
            assert current.history.snapshot() == original
            scans.now = 121
        finally:
            release.set()
            await manual
        assert current.history.snapshot() == original
        assert not old_starts
        assert not old.scanner.current()
        assert old.scanner.deadlines() == []
        old.scanner.evaluate(scan=True)
        old.last_update_success = False
        old.async_update_listeners()
        old._expire()
        assert current.history.snapshot() == original
    assert not any(
        event.data["entity_id"] == TRACKER
        and event.data["new_state"]
        and event.data["new_state"].state == "home"
        for event in changes
    )
    state = hass.states.get(TRACKER)
    assert state is not None and state.state == "not_home"


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("when", ["before", "during"])
async def test_obsolete_generation_is_not_a_real_coordinator_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    when: str,
) -> None:
    """GLM-1: semantic generation changes preserve evidence and DUC success."""
    await track_phone(hass, config_entry)
    for now in (30, 60, 90):
        await scan(hass, config_entry, scans, now)
    coordinator = runtime(config_entry).bluetooth
    assert isinstance(coordinator, BluetoothCoordinator)
    original, data = coordinator.history.snapshot(), coordinator.data

    async def obsolete_read(
        _session: object, _device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        # This is the same semantic epoch bump used for changed subentry membership.
        coordinator.history.generation += 1
        return []

    scans.now = 120
    with patch(
        "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
        obsolete_read,
    ):
        if when == "before":
            coordinator.history.generation += 1
        await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data == data
    assert coordinator.history.snapshot() == original
    state = hass.states.get(TRACKER)
    assert state is not None and state.state == "not_home"


async def test_actual_ha_stop_drains_same_worker_after_blocked_executor_write(
    evidence: tuple[BluetoothHistory, list[float]],
    tmp_path: Path,
) -> None:
    """ASTRA-R1-02: normal stop waits for old I/O, then invalidation/new snapshot."""
    history, now = evidence
    hass = history.hass
    history.confirm(PHONE, "not_home", None, 0, "live")
    entered, written, stopping = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release = ThreadEvent()
    order: list[str] = []
    io = file_backend(history, str(tmp_path / history._store.key))
    real_write, real_remove = io._write, history._store.async_remove
    loop = asyncio.get_running_loop()
    calls = 0

    def blocked_write(mode: str, data: str | bytes) -> None:
        nonlocal calls
        calls += 1
        payload = json.loads(data)["data"]
        if calls == 1:
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5), "test did not release executor write"
        real_write(mode, data)
        order.append("write:" + payload["trackers"][PHONE]["state"])
        if calls == 1:
            loop.call_soon_threadsafe(written.set)

    async def remove() -> None:
        order.append("remove")
        await real_remove()

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, callback(lambda _event: stopping.set())
    )
    with (
        patch.object(io, "_write", blocked_write),
        patch.object(history._store, "async_remove", remove),
    ):
        history._enqueue()
        await asyncio.wait_for(entered.wait(), 5)
        worker = history._worker
        assert worker is not None
        now[0] = 20
        hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": False}
        )
        hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": True}
        )
        history.confirm(PHONE, "home", 10, 20, "live", WALL + 10)
        history._enqueue()
        stop = asyncio.create_task(hass.async_stop(force=True))
        try:
            await asyncio.wait_for(stopping.wait(), 5)
            await asyncio.sleep(0)
            assert not worker.cancelled()
            assert not worker.done()
            assert history._worker is worker
        finally:
            release.set()
            await asyncio.wait_for(written.wait(), 5)
            await asyncio.wait_for(stop, 5)
        assert history._worker is worker and not worker.cancelled()
        assert not history._queue
    assert order == ["write:not_home", "remove", "write:home"]
    loaded = await load_file_history(history, now[0])
    row = loaded.trackers[PHONE]
    assert (row.state, row.sighted, row.confirmed, row.expires) == ("home", 10, 20, 320)


async def test_registry_bind_promotion_and_load_use_supported_scoped_apis(
    evidence: tuple[BluetoothHistory, list[float]],
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ASTRA-R1-03: exact normal bindings need no deprecated composite lookups."""
    history, now = evidence
    source = history.source_reply("source", 0)
    original = (
        source.last_success,
        source.deadline,
        source.last_success_utc,
        source.deadline_utc,
    )
    registered = device_registry.async_get_or_create(
        config_entry_id=history.entry.entry_id, identifiers={("google_home", "source")}
    )
    caplog.clear()
    now[0] = 30
    history.promote_bindings()
    assert source.row_id == registered.id
    assert (
        source.last_success,
        source.deadline,
        source.last_success_utc,
        source.deadline_utc,
    ) == original
    history.source_reply("other", 30)
    await history.async_flush()
    loaded = BluetoothHistory(history.hass, history.entry)
    await loaded.async_load(lambda: now[0])
    assert loaded.sources[registered.id].source_id == "source"
    assert not any(
        "deprecated" in record.getMessage().lower()
        and "google_home" in record.getMessage()
        for record in caplog.records
    )
