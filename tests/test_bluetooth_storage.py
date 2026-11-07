"""Invented evidence fixtures for restart age, intent observation and Store limits."""

# Exact interval/Store ordering fixtures inspect internals; their expectations
# are original ages, state sequences and a subsequent genuine Store load.
# ruff: noqa: SLF001

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
import json
import math
from unittest.mock import Mock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.bluetooth import BluetoothScanner, TrackerState
from custom_components.google_home.bluetooth_storage import (
    BluetoothHistory,
    SourceEvidence,
    async_history,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# pylint: disable=wrong-import-order,protected-access
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.util.file import WriteError

from .test_bluetooth import PHONE, Speakers, subentry

# pylint: enable=wrong-import-order

WALL = 1800000000.0


@contextmanager
def owned_scans(speakers: Speakers) -> Iterator[None]:
    """Fake only requests; history still uses the real HA registry."""
    with (
        patch(
            "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
            speakers.async_get_bluetooth_scan_results,
        ),
        patch(
            "custom_components.google_home.bluetooth.async_start_bluetooth_scan",
            speakers.async_start_bluetooth_scan,
        ),
    ):
        yield


@pytest.fixture(name="evidence")
async def fixture_evidence(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> AsyncIterator[tuple[BluetoothHistory, list[float]]]:
    """Pair UTC and a resettable monotonic clock without real radio traffic."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(
        config_entry, subentry({"mac": "AA:BB:CC:DD:EE:FF"})
    )
    now = [0.0]
    with (
        patch(
            "custom_components.google_home.bluetooth_storage.utc_timestamp",
            lambda: WALL + now[0],
        ),
        patch("custom_components.google_home.bluetooth.monotonic", lambda: now[0]),
    ):
        history = async_history(hass, config_entry)
        await history.async_load(lambda: now[0])
        yield history, now
        await history.async_flush()


def scanner_for(history: BluetoothHistory, speakers: Speakers) -> BluetoothScanner:
    """Create a new scanner instance, retaining only entry-owned evidence."""
    account = Mock(
        data={device.device_id: device for device in speakers.devices},
        hass=history.hass,
        config_entry=history.entry,
    )
    return BluetoothScanner(
        Mock(), account, history.entry.subentries.values(), [], history
    )


@pytest.mark.parametrize("state", ["home", "not_home"])
async def test_restore_original_age_and_expire_without_polling(
    evidence: tuple[BluetoothHistory, list[float]], state: str
) -> None:
    """Reload/save never renew a decision; original E expires without a scan."""
    history, now = evidence
    history.confirm(PHONE, state, -30, 0, "live", WALL - 30)
    speakers = Speakers("A")
    scanner = scanner_for(history, speakers)
    for time in (75, 150, 299):
        now[0] = time
        scanner = scanner_for(history, speakers)
        assert scanner.evaluate()[PHONE].state == state
        assert history.trackers[PHONE].confirmed == 0
        assert history.snapshot()["trackers"] == {
            PHONE: {
                "revision": history.trackers[PHONE].config_revision,
                "state": state,
                "sighted": WALL - 30,
                "confirmed": WALL,
                "expires": WALL + 300,
            }
        }
        await history.async_flush()
    now[0] = 300
    assert scanner.evaluate()[PHONE].state == TrackerState.UNAVAILABLE
    # Expired evidence is ineligible for a new instance, not re-labelled fresh.
    assert (
        scanner_for(history, speakers).evaluate()[PHONE].state == TrackerState.UNKNOWN
    )


async def test_full_process_load_preserves_utc_and_shortens_only_unmatched(
    evidence: tuple[BluetoothHistory, list[float]], device_registry: dr.DeviceRegistry
) -> None:
    """Registry identity survives a new manager; anonymous history uses original L+90."""
    history, now = evidence
    registered = device_registry.async_get_or_create(
        config_entry_id=history.entry.entry_id, identifiers={("google_home", "known")}
    )
    history.source_reply("known", 0)
    history.source_reply("anonymous", 0)
    history.confirm(PHONE, "not_home", None, 0, "live")
    await history.async_flush()
    now[0] = 60
    loaded = BluetoothHistory(history.hass, history.entry)
    # New process monotonic origin 1000, UTC age remains 60.
    await loaded.async_load(lambda: 1000)
    by_id = {row.source_id: row for row in loaded.sources.values()}
    assert by_id["known"].row_id == registered.id
    assert (by_id["known"].last_success, by_id["known"].deadline) == (940, 1240)
    assert (by_id[None].last_success, by_id[None].deadline) == (940, 1030)
    assert (loaded.trackers[PHONE].confirmed, loaded.trackers[PHONE].expires) == (
        940,
        1240,
    )
    now[0] = 91
    again = BluetoothHistory(history.hass, history.entry)
    await again.async_load(lambda: 2000)
    assert [row.source_id for row in again.sources.values()] == ["known"]
    now[0] = 301
    expired = BluetoothHistory(history.hass, history.entry)
    await expired.async_load(lambda: 3000)
    assert not expired.trackers and not expired.sources


@pytest.mark.parametrize(
    "change", ["tracking", "polling", "disabled", "identity", "removed"]
)
async def test_intent_observer_invalidates_without_loaded_hooks(
    evidence: tuple[BluetoothHistory, list[float]], change: str
) -> None:
    """A failed/not-yet-loaded entry can be toggled twice before setup succeeds."""
    history, now = evidence
    history.confirm(PHONE, "home", 0, 0, "live", WALL)
    await history.async_flush()
    now[0] = 10
    hass, entry = history.hass, history.entry
    if change == "tracking":
        hass.config_entries.async_update_entry(
            entry, options={"bluetooth_tracking": False}
        )
        hass.config_entries.async_update_entry(
            entry, options={"bluetooth_tracking": True}
        )
    elif change == "polling":
        hass.config_entries.async_update_entry(entry, pref_disable_polling=True)
        hass.config_entries.async_update_entry(entry, pref_disable_polling=False)
    elif change == "disabled":
        with patch.object(hass.config_entries, "async_reload", return_value=True):
            await hass.config_entries.async_set_disabled_by(
                entry.entry_id, ConfigEntryDisabler.USER
            )
            await hass.config_entries.async_set_disabled_by(entry.entry_id, None)
    elif change == "identity":
        hass.config_entries.async_update_subentry(
            entry, entry.subentries[PHONE], data={"mac": "00:11:22:33:44:55"}
        )
    else:
        hass.config_entries.async_remove_subentry(entry, PHONE)
    assert not history.trackers
    assert (
        scanner_for(history, Speakers("A")).evaluate().get(PHONE) is None
        or scanner_for(history, Speakers("A")).evaluate()[PHONE].state
        == TrackerState.UNKNOWN
    )
    await history.async_flush()
    loaded = BluetoothHistory(hass, entry)
    await loaded.async_load(lambda: 10)
    assert not loaded.trackers


async def test_rename_preserves_evidence(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Title-only entry/subentry changes preserve the original evidence lease."""
    history, _ = evidence
    history.confirm(PHONE, "not_home", None, 0, "live")
    generation = history.generation
    history.hass.config_entries.async_update_entry(history.entry, title="Renamed")
    history.hass.config_entries.async_update_subentry(
        history.entry, history.entry.subentries[PHONE], title="Renamed tracker"
    )
    assert history.generation == generation
    assert history.trackers[PHONE].expires == 300


@pytest.mark.parametrize(
    ("healthy", "covered", "expected"),
    [
        (True, True, "not_home"),
        (True, False, "unavailable"),
        (False, True, "unavailable"),
    ],
)
async def test_no_scan_at_simultaneous_expiry(
    evidence: tuple[BluetoothHistory, list[float]],
    healthy: bool,
    covered: bool,
    expected: str,
) -> None:
    """A consumed D=E event owns exactly one coverage-backed C=300/E=600 decision."""
    history, now = evidence
    history.confirm(PHONE, "not_home", -120, 0, "live", WALL - 120)
    speakers = Speakers("A", "B")
    scanner = scanner_for(history, speakers)
    with owned_scans(speakers):
        scanner._update_speakers()
        history.sources["a"] = SourceEvidence(
            "a", "a", 270, 570, WALL + 270, WALL + 570
        )
        history.sources["b"] = SourceEvidence("b", "b", 0, 300, WALL, WALL + 300)
        a = scanner._speakers["a"]
        if covered:
            a.run_start, a.covered_until = 0, 270
        now[0] = 299
        assert scanner.evaluate(healthy=healthy)[PHONE].state == "not_home"
        now[0] = 300
        assert scanner.evaluate(healthy=healthy)[PHONE].state == expected
        assert not speakers.asked
        row = history.trackers[PHONE]
        assert (row.confirmed, row.expires) == (
            (300, 600) if healthy and covered else (0, 300)
        )
        assert (row.sighted, row.sighted_utc) == (-120, WALL - 120)
        assert (history.sources["a"].last_success, history.sources["a"].deadline) == (
            270,
            570,
        )
        now[0] = 301
        assert scanner.evaluate(healthy=healthy)[PHONE].state == expected
        assert history.trackers[PHONE] is row
        reloaded = scanner_for(history, speakers)
        assert reloaded.evaluate()[PHONE].state == (
            "not_home" if healthy and covered else "unknown"
        )
        assert all(scan.run_start is None for scan in reloaded._speakers.values())


@pytest.mark.parametrize("timer", [180, 316])
async def test_actual_expiry_time_and_d_before_e(
    evidence: tuple[BluetoothHistory, list[float]], timer: int
) -> None:
    """Early D creates a new lease; late callbacks cannot backdate stale coverage."""
    history, now = evidence
    history.confirm(PHONE, "not_home", None, 0, "live")
    speakers = Speakers("A", "B")
    scanner = scanner_for(history, speakers)
    with owned_scans(speakers):
        scanner._update_speakers()
        history.sources["a"] = SourceEvidence(
            "a", "a", 150 if timer == 180 else 270, 570, WALL, WALL + 570
        )
        history.sources["b"] = SourceEvidence(
            "b",
            "b",
            -120 if timer == 180 else 0,
            180 if timer == 180 else 300,
            WALL - 120,
            WALL + 180,
        )
        scanner._speakers["a"].run_start = 0
        scanner._speakers["a"].covered_until = 150 if timer == 180 else 270
        now[0] = timer
        assert scanner.evaluate()[PHONE].state == (
            "not_home" if timer == 180 else "unavailable"
        )
        assert (history.trackers[PHONE].confirmed, history.trackers[PHONE].expires) == (
            (180, 480) if timer == 180 else (0, 300)
        )


async def test_swallowed_store_failure_preserves_memory_but_can_restore_old_disk(
    evidence: tuple[BluetoothHistory, list[float]], caplog: pytest.LogCaptureFixture
) -> None:
    """Real Store catches WriteError; failed unlink leaves older valid data possible."""
    history, now = evidence
    history.confirm(PHONE, "home", 0, 0, "live", WALL)
    await history.async_flush()
    with (
        patch.object(Store, "async_remove", side_effect=OSError("unwritable")),
        patch.object(Store, "_async_write_data", side_effect=WriteError("unwritable")),
    ):
        history.hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": False}
        )
        history.hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": True}
        )
        await history.async_flush()
    assert not history.trackers
    assert "Error writing config" in caplog.text
    assert history._store._data is None
    now[0] = 60
    loaded = BluetoothHistory(history.hass, history.entry)
    await loaded.async_load(lambda: 60)
    assert (
        loaded.trackers[PHONE].expires == 300
    )  # Accepted full-process durability limit.


async def test_delayed_write_is_ordered_before_invalidation_and_reload(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Cancelling a waiter cannot cancel the domain worker or overtake its write."""
    history, _ = evidence
    history.confirm(PHONE, "not_home", None, 0, "live")
    entered, release = asyncio.Event(), asyncio.Event()
    real_write = Store._async_write_data
    calls = 0

    async def delayed(store: Store[dict[str, object]], data: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        await real_write(store, data)

    with patch.object(Store, "_async_write_data", delayed):
        waiter = asyncio.create_task(history.async_flush())
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        history.hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": False}
        )
        history.hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": True}
        )
        assert not history.trackers
        next_flush = asyncio.create_task(history.async_flush())
        await asyncio.sleep(0)
        assert not next_flush.done()
        release.set()
        await next_flush
    loaded = BluetoothHistory(history.hass, history.entry)
    await loaded.async_load(lambda: 0)
    assert not loaded.trackers


async def test_privacy_and_clock_discontinuity(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Persist only opaque row keys and ages; wall jumps cannot renew evidence."""
    history, now = evidence
    history.source_reply("invented-private-google-id", 0)
    history.confirm(PHONE, "home", 0, 0, "live", WALL)
    payload = json.dumps(history.snapshot())
    for forbidden in (
        "invented-private-google-id",
        "AA:BB:CC:DD:EE:FF",
        "mac",
        "irk",
        "auth_token",
        "name",
        "monotonic",
    ):
        assert forbidden not in payload
    now[0] = 30
    assert history.check_clock(30)
    assert not history.check_clock(60)
    assert not history.trackers and not history.sources


@pytest.mark.parametrize(
    "payload",
    [
        {"policy": 1, "sources": [], "trackers": []},
        {"policy": 1, "sources": {"bad": []}, "trackers": {PHONE: []}},
        {
            "policy": 1,
            "sources": {"bad": {"last": True, "deadline": WALL + 300}},
            "trackers": {"removed": {}},
        },
        {
            "policy": 1,
            "sources": {"bad": {"last": WALL + 1, "deadline": WALL + 301}},
            "trackers": {
                PHONE: {"confirmed": WALL, "expires": WALL + 301, "state": "home"}
            },
        },
        {
            "policy": 1,
            "sources": {"bad": {"last": math.inf, "deadline": WALL}},
            "trackers": {
                PHONE: {
                    "confirmed": WALL,
                    "expires": WALL + 300,
                    "state": "unavailable",
                }
            },
        },
        {
            "policy": 1,
            "trackers": {
                PHONE: {
                    "confirmed": WALL,
                    "expires": WALL + 300,
                    "state": "home",
                    "sighted": WALL + 1,
                }
            },
        },
        {
            "policy": 1,
            "trackers": {
                PHONE: {
                    "confirmed": WALL,
                    "expires": WALL + 300,
                    "state": "home",
                    "sighted": "bad",
                }
            },
        },
        {
            "policy": 1,
            "trackers": {
                PHONE: {"confirmed": WALL, "expires": WALL + 300, "state": "home"}
            },
        },
    ],
)
async def test_invalid_saved_rows_are_cold(
    evidence: tuple[BluetoothHistory, list[float]], payload: dict[str, object]
) -> None:
    """Corrupt/future/incompatible rows never acquire current freshness on load."""
    history, _ = evidence
    rows = payload.get("trackers")
    for row in rows.values() if isinstance(rows, dict) else []:
        if isinstance(row, dict):
            row.setdefault("revision", "invented-config-revision")
    with patch.object(Store, "async_load", return_value=payload):
        loaded = BluetoothHistory(history.hass, history.entry)
        await loaded.async_load(lambda: 0)
    assert not loaded.sources and not loaded.trackers


async def test_load_error_is_cold_and_early_invalidation_wins(
    evidence: tuple[BluetoothHistory, list[float]],
    hass_storage: dict[str, dict[str, object]],
) -> None:
    """A Store that refuses its file is nonfatal, and off/on during load can't restore home."""
    history, _ = evidence
    history.confirm(PHONE, "home", 0, 0, "live", WALL)
    await history.async_flush()
    # Store refuses the saved home that would otherwise restore
    hass_storage[history._store.key]["version"] = 2
    loaded = BluetoothHistory(history.hass, history.entry)
    await loaded.async_load(lambda: 0)
    assert not loaded.trackers
    # Saving goes on, replacing the refused file
    await loaded.async_flush()
    assert hass_storage[history._store.key]["version"] == 1
    pending = BluetoothHistory(history.hass, history.entry)
    pending.schedule_save()
    pending._enqueue()  # Before load: do not overwrite a file we have not read.
    assert pending._worker is None
    history.hass.config_entries.async_update_entry(
        history.entry, options={"bluetooth_tracking": False}
    )
    pending.observe()
    history.hass.config_entries.async_update_entry(
        history.entry, options={"bluetooth_tracking": True}
    )
    pending.observe()
    with patch.object(
        Store,
        "async_load",
        return_value={
            "policy": 1,
            "trackers": {
                PHONE: {
                    "state": "home",
                    "confirmed": WALL,
                    "expires": WALL + 300,
                    "sighted": WALL,
                }
            },
        },
    ):
        await pending.async_load(lambda: 0)
    assert not pending.trackers
    await pending.async_flush()


async def test_stale_queued_write_and_entry_removal(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Skip obsolete queued generations; removal cannot be undone by final flush."""
    history, _ = evidence
    history.confirm(PHONE, "home", 0, 0, "live", WALL)
    history._enqueue()
    history.generation += 1  # The queued generation has not started I/O yet.
    await history.async_flush()
    await history.async_remove()
    await history.async_flush()
    assert (
        await Store[dict[str, object]](
            history.hass, 1, f"google_home.bluetooth.{history.entry.entry_id}"
        ).async_load()
        is None
    )


async def test_remove_failure_is_memory_final(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """An unlink error cannot keep live evidence for a removed entry."""
    history, _ = evidence
    history.confirm(PHONE, "not_home", None, 0, "live")
    await history.async_flush()
    with patch.object(Store, "async_remove", side_effect=OSError("unwritable")):
        await history.async_remove()
    assert not history.trackers and history._removed


async def test_successful_graph_exact_removal_and_late_reply(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Filtered-list loss is not removal; full-graph absence invalidates an owned read."""
    history, now = evidence
    speakers = Speakers("A", "B")
    scanner = scanner_for(history, speakers)
    with owned_scans(speakers):
        await scanner.async_update()
        now[0] = 30
        await scanner.async_update()
        assert {row.source_id for row in history.sources.values()} == {"a", "b"}
        # B loses its usable object/token, but not its graph membership/lease.
        scanner._account.data.pop("b")
        now[0] = 60
        await scanner.async_update()
        assert "b" in {row.source_id for row in history.sources.values()}
        # Successful full graph explicitly removes B. Its successful in-flight
        # response below must be rejected before touching L or sightings.
        scanner._account.data["b"] = speakers.devices[1]
        scanner._account.client.bluetooth_source_ids = {"a", "b"}
        await scanner.async_update()

        async def late(_session: object, _device: object) -> list[object]:
            scanner._account.client.bluetooth_source_ids = {"a"}
            return []

        with patch(
            "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
            side_effect=late,
        ):
            now[0] = 90
            await scanner.async_update()
        assert "b" not in {row.source_id for row in history.sources.values()}
        speakers.asked.clear()
        now[0] = 120
        await scanner.async_update()
        assert "b" not in speakers.asked
        # A later successful roster can list it again; no count/name matching.
        scanner._account.client.bluetooth_source_ids = {"a", "b"}
        now[0] = 150
        await scanner.async_update()
        assert "b" in speakers.asked


async def test_zero_healthy_sources_and_return_rebuild(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Expired source retries, but a returning empty reply is not 90s coverage."""
    history, now = evidence
    speakers = Speakers("A")
    scanner = scanner_for(history, speakers)
    with owned_scans(speakers):
        for t in (0, 30, 60, 90):
            now[0] = t
            assert (await scanner.async_update())[PHONE].state in {
                "unknown",
                "not_home",
            }
        speakers.failing.add("a")
        result = {}
        for t in (120, 390):
            now[0] = t
            result = await scanner.async_update()
        assert result[PHONE].state == "unavailable"
        assert not history.sources
        assert speakers.asked.count("a") >= 6  # Inactive still attempted.
        speakers.failing.clear()
        for t in (420, 450, 480):
            now[0] = t
            assert (await scanner.async_update())[PHONE].state == "unavailable"
        now[0] = 510
        assert (await scanner.async_update())[PHONE].state == "not_home"
        assert history.trackers[PHONE].confirmed == 510


async def test_non_identity_metadata_does_not_renew_or_invalidate(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Future non-identity options cannot become freshness or restore identity."""
    history, now = evidence
    history.source_reply("a", 0)
    history.confirm(PHONE, "not_home", None, 0, "live")
    before, generation = history.snapshot(), history.generation
    now[0] = 30
    data = dict(history.entry.subentries[PHONE].data)
    data["invented_future_non_identity_option"] = 0
    history.hass.config_entries.async_update_subentry(
        history.entry, history.entry.subentries[PHONE], data=data
    )
    assert history.generation == generation
    assert history.snapshot() == before
    scanner = scanner_for(history, Speakers("A"))
    assert scanner.evaluate()[PHONE].state == "not_home"
    assert history.snapshot() == before
    data["invented_future_non_identity_option"] = 90
    history.hass.config_entries.async_update_subentry(
        history.entry, history.entry.subentries[PHONE], data=data
    )
    assert history.snapshot() == before


async def test_obsolete_scan_cannot_confirm_after_disable_cycle(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """A successful late response cannot undo inline off/on invalidation."""
    history, now = evidence
    speakers = Speakers("A")
    scanner = scanner_for(history, speakers)
    with owned_scans(speakers):
        await scanner.async_update()
        history.confirm(PHONE, "home", 0, 0, "live", WALL)

        async def disable_during_read(
            _session: object, _device: object
        ) -> list[object]:
            history.hass.config_entries.async_update_entry(
                history.entry, options={"bluetooth_tracking": False}
            )
            history.hass.config_entries.async_update_entry(
                history.entry, options={"bluetooth_tracking": True}
            )
            return []

        now[0] = 30
        with (
            patch(
                "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
                side_effect=disable_during_read,
            ),
        ):
            await scanner.async_update()
        assert not history.trackers and not history.sources
        assert not scanner.current()


async def test_missing_config_revision_is_cold(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Unversioned tracker evidence never migrates by inventing a revision/age."""
    history, _ = evidence
    history.confirm(PHONE, "not_home", None, 0, "live")
    payload = history.snapshot()
    rows = payload["trackers"]
    assert isinstance(rows, dict)
    rows[PHONE].pop("revision")
    with patch.object(Store, "async_load", return_value=payload):
        loaded = BluetoothHistory(history.hass, history.entry)
        await loaded.async_load(lambda: 0)
    assert not loaded.trackers


async def test_delayed_load_pairs_clocks_after_io(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Ten seconds of storage I/O is not an extra ten seconds of evidence age."""
    history, now = evidence
    history.confirm(PHONE, "not_home", None, 0, "live")
    await history.async_flush()
    entered, release = asyncio.Event(), asyncio.Event()
    real_load = Store.async_load

    async def delayed(store: Store[dict[str, object]]) -> dict[str, object] | None:
        entered.set()
        await release.wait()
        return await real_load(store)

    loaded = BluetoothHistory(history.hass, history.entry)
    with patch.object(Store, "async_load", delayed):
        task = asyncio.create_task(loaded.async_load(lambda: now[0]))
        await entered.wait()
        now[0] = 10
        release.set()
        await task
    assert (loaded.trackers[PHONE].confirmed, loaded.trackers[PHONE].expires) == (
        0,
        300,
    )
    assert loaded.check_clock(10)
    assert loaded.trackers[PHONE].expires == 300


async def test_load_completion_rearms_dropped_invalidation_attempt(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """Off/on during a slow load attempts disk invalidation once loading completes."""
    history, now = evidence
    history.confirm(PHONE, "home", 0, 0, "live", WALL)
    await history.async_flush()
    entered, release = asyncio.Event(), asyncio.Event()
    real_load = Store.async_load

    async def delayed(store: Store[dict[str, object]]) -> dict[str, object] | None:
        entered.set()
        await release.wait()
        return await real_load(store)

    pending = BluetoothHistory(history.hass, history.entry)
    with patch.object(Store, "async_load", delayed):
        task = asyncio.create_task(pending.async_load(lambda: now[0]))
        await entered.wait()
        history.hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": False}
        )
        pending.observe()
        history.hass.config_entries.async_update_entry(
            history.entry, options={"bluetooth_tracking": True}
        )
        pending.observe()
        pending._enqueue()  # The first coalescing timer fires before load finishes.
        first_timer = pending._save_cancel
        assert pending._worker is None and first_timer is None
        now[0] = 10
        release.set()
        await task
    assert not pending.trackers
    timer = pending._save_cancel
    assert timer is not None
    with patch.object(
        pending._store, "async_remove", wraps=pending._store.async_remove
    ) as remove:
        pending._enqueue()  # Dispatch its coalescing callback, no unrelated flush/scan.
        await history.hass.async_block_till_done(wait_background_tasks=True)
        assert remove.call_count == 1
    loaded = BluetoothHistory(history.hass, history.entry)
    await loaded.async_load(lambda: now[0])
    assert not loaded.trackers


@pytest.mark.parametrize("phase", ["get", "post"])
@pytest.mark.parametrize("transition", ["disable", "relist", "reset"])
async def test_old_404_cannot_remove_current_requirements(
    evidence: tuple[BluetoothHistory, list[float]], phase: str, transition: str
) -> None:
    """Every request completion must still own the source epoch and instance."""
    from custom_components.google_home.bluetooth import BluetoothScanUnsupported  # noqa: PLC0415 # pylint: disable=import-outside-toplevel

    history, now = evidence
    speakers = Speakers("A")
    scanner = scanner_for(history, speakers)
    observed: list[tuple[float, float]] = []
    with owned_scans(speakers):
        await scanner.async_update()
        history.source_reply("a", 0)

        async def obsolete(_session: object, _device: object) -> list[object]:
            if transition == "disable":
                history.hass.config_entries.async_update_entry(
                    history.entry, options={"bluetooth_tracking": False}
                )
                history.hass.config_entries.async_update_entry(
                    history.entry, options={"bluetooth_tracking": True}
                )
            elif transition == "relist":
                scanner._account.client.bluetooth_source_ids = set()
                scanner.evaluate()
                scanner._account.client.bluetooth_source_ids = {"a"}
                scanner.evaluate()
                history.source_reply("a", now[0])
            else:
                history.generation += 1
                scanner.reset_clock()
            observed.extend(
                (row.last_success, row.deadline) for row in history.sources.values()
            )
            raise BluetoothScanUnsupported("old endpoint")

        target = (
            "async_get_bluetooth_scan_results"
            if phase == "get"
            else "async_start_bluetooth_scan"
        )
        now[0] = 30
        with patch(
            f"custom_components.google_home.bluetooth.{target}", side_effect=obsolete
        ):
            await scanner.async_update()
        assert [
            (row.last_success, row.deadline) for row in history.sources.values()
        ] == observed
        assert "a" not in scanner._unsupported


@pytest.mark.parametrize("field", ["ip_address", "auth_token"])
async def test_mutated_endpoint_cannot_supply_old_results(
    evidence: tuple[BluetoothHistory, list[float]], field: str
) -> None:
    """Changing the same account object rejects old sightings and restarts ownership."""
    from .test_bluetooth import heard  # noqa: PLC0415 # pylint: disable=import-outside-toplevel

    history, now = evidence
    speakers = Speakers("A")
    scanner = scanner_for(history, speakers)
    with owned_scans(speakers):
        await scanner.async_update()
        history.source_reply("a", 0)

        async def replaced(
            _session: object, _device: object
        ) -> list[BluetoothJsonDict]:
            setattr(speakers.devices[0], field, "replacement")
            return [heard("AA:BB:CC:DD:EE:FF")]

        now[0] = 30
        with patch(
            "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
            side_effect=replaced,
        ):
            assert (await scanner.async_update())[PHONE].state == "unknown"
        assert next(iter(history.sources.values())).last_success == 0
        assert scanner.tracked[0].last_sighted is None
        assert scanner._speakers["a"].run_start is None
        now[0] = 60
        await scanner.async_update()
        speakers.results["a"] = [heard("AA:BB:CC:DD:EE:FF")]
        now[0] = 90
        assert (await scanner.async_update())[PHONE].state == "home"
        assert scanner.tracked[0].last_sighted == 60


async def test_later_registry_binding_promotes_without_renewing(
    evidence: tuple[BluetoothHistory, list[float]], device_registry: dr.DeviceRegistry
) -> None:
    """Normal registry creation later makes the existing exact source restorable."""
    history, now = evidence
    original = history.source_reply("later", 0)
    original_id = original.row_id
    registered = device_registry.async_get_or_create(
        config_entry_id=history.entry.entry_id, identifiers={("google_home", "later")}
    )
    now[0] = 30
    history.promote_bindings()
    assert original_id not in history.sources
    assert history.sources[registered.id] is original
    assert (
        original.last_success,
        original.deadline,
        original.last_success_utc,
        original.deadline_utc,
    ) == (0, 300, WALL, WALL + 300)
    await history.async_flush()
    now[0] = 60
    loaded = BluetoothHistory(history.hass, history.entry)
    await loaded.async_load(lambda: 1000)
    assert (
        loaded.sources[registered.id].source_id,
        loaded.sources[registered.id].deadline,
    ) == ("later", 1240)


async def test_unexpected_scan_failure_drains_sibling_requests(
    evidence: tuple[BluetoothHistory, list[float]],
) -> None:
    """A failed update cannot leave another request writing later shared evidence."""
    history, now = evidence
    speakers = Speakers("A", "B")
    scanner = scanner_for(history, speakers)
    entered, cancelled = asyncio.Event(), asyncio.Event()
    with owned_scans(speakers):
        await scanner.async_update()

        async def unexpected(
            _session: object, device: GoogleHomeDevice
        ) -> list[object]:
            if device.device_id == "a":
                await entered.wait()
                raise RuntimeError("unexpected request failure")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return []

        now[0] = 30
        with (
            patch(
                "custom_components.google_home.bluetooth.async_get_bluetooth_scan_results",
                side_effect=unexpected,
            ),
            pytest.raises(RuntimeError, match="unexpected request failure"),
        ):
            await scanner.async_update()
        assert cancelled.is_set()
        assert not history.sources and not history.trackers
