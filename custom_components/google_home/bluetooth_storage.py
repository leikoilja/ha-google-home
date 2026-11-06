"""Bounded Bluetooth evidence, retained across reloads and best-effort restarts.

The domain owns one Store/worker per entry. A save is not a durable-success
acknowledgement; memory invalidations win even when disk operations fail.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
from math import isfinite
from typing import Final, cast
from uuid import uuid4

from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BLUETOOTH_CONFIRMATION_LEASE,
    BLUETOOTH_MATCHED_SOURCE_TIMEOUT,
    BLUETOOTH_UNMATCHED_SOURCE_TIMEOUT,
    CONF_BLUETOOTH_EXCLUDED,
    CONF_BLUETOOTH_TRACKING,
    CONF_IRK,
    DOMAIN,
    SUBENTRY_BLUETOOTH_DEVICE,
)
from .types import GoogleHomeConfigEntry

_LOGGER = logging.getLogger(__name__)
_SAVE_DELAY: Final = 5
_HISTORY_KEY: Final = f"{DOMAIN}_bluetooth_history"


def utc_timestamp() -> float:
    """Read UTC alongside an evidence event, never as its replacement age."""
    return dt_util.utcnow().timestamp()


@dataclass
class SourceEvidence:
    """A reply lease; binding is memory-only, row ID is safe to persist."""

    row_id: str
    source_id: str | None
    last_success: float
    deadline: float
    last_success_utc: float
    deadline_utc: float


@dataclass
class PresenceEvidence:
    """Latest eligible tracker decision, with original paired timestamps."""

    state: str
    sighted: float | None
    confirmed: float
    expires: float
    sighted_utc: float | None
    confirmed_utc: float
    expires_utc: float
    provenance: str
    config_revision: str


def _number(value: object) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    ):
        return float(value)
    return None


class BluetoothHistory:
    """Entry-lifetime evidence and serialized Store operations."""

    def __init__(self, hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> None:
        """Create the single memory/I/O owner before any setup await."""
        self.hass = hass
        self.entry = entry
        self.sources: dict[str, SourceEvidence] = {}
        self.trackers: dict[str, PresenceEvidence] = {}
        self.generation = 0
        self._scanner_instance: object | None = None
        self._store = Store[dict[str, object]](
            hass,
            1,
            f"{DOMAIN}.bluetooth.{entry.entry_id}",
            private=True,
            atomic_writes=True,
        )
        self._loaded = False
        self._invalidated: set[str] = set()
        self._intent: tuple[bool, bool, bool] | None = None
        self._identities: dict[str, tuple[object, object]] = {}
        self._revisions: dict[str, str] = {}
        self._excluded: frozenset[str] = frozenset()
        self._offset: float | None = None
        self._save_cancel: asyncio.TimerHandle | None = None
        self._queue: list[tuple[int, bool, dict[str, object]]] = []
        self._worker: asyncio.Task[None] | None = None
        self._removed = False
        self._remove_pending = False
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_stop)
        self.observe()

    def claim_scanner(self) -> object:
        """Give a newly set-up scanner exclusive ownership without renewing ages."""
        self._scanner_instance = object()
        return self._scanner_instance

    def owns_scanner(self, instance: object) -> bool:
        """Keep ordinary setup lifetime separate from semantic config generation."""
        return self._scanner_instance is instance

    def retire_scanner(self, instance: object) -> None:
        """An old unload must neither retain ownership nor retire a newer setup."""
        if self.owns_scanner(instance):
            self._scanner_instance = None

    @callback
    def observe(self) -> None:
        """See semantic transitions inline, including failed/unloaded entries."""
        intent = (
            bool(self.entry.options.get(CONF_BLUETOOTH_TRACKING, False)),
            not self.entry.pref_disable_polling,
            self.entry.disabled_by is None,
        )
        identities = {
            sub.subentry_id: (sub.data.get(CONF_IRK), sub.data.get("mac"))
            for sub in self.entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE)
        }
        excluded = frozenset(self.entry.options.get(CONF_BLUETOOTH_EXCLUDED, []))
        changed = self._intent is not None and (
            intent != self._intent
            or identities != self._identities
            or excluded != self._excluded
        )
        invalid = {
            key
            for key, value in self._identities.items()
            if identities.get(key) != value
        }
        if not all(intent) or (self._intent is not None and intent != self._intent):
            invalid |= (
                self._identities.keys() | identities.keys() | self.trackers.keys()
            )
        self._intent, self._identities, self._excluded = intent, identities, excluded
        if changed:
            self.generation += 1
        if invalid:
            self._invalidated.update(invalid)
            for key in invalid:
                self.trackers.pop(key, None)
                self._revisions[key] = uuid4().hex
            self._remove_pending = True
            self.schedule_save()

    async def async_load(self, clock: Callable[[], float]) -> None:
        """Load once, before account refresh can remove registry identity rows."""
        if self._loaded:
            return
        try:
            data = await self._store.async_load()
        except OSError, ValueError:
            _LOGGER.warning("Could not load Bluetooth continuity; starting fresh")
            data = None
        self._loaded = True
        # Both readings belong to the same post-I/O instant.
        now, wall = clock(), utc_timestamp()
        if self._remove_pending:
            self.schedule_save()
        self._offset = wall - now
        if not isinstance(data, dict) or data.get("policy") != 1:
            return
        registry = dr.async_get(self.hass)
        rows = data.get("sources", {})
        for key, raw in rows.items() if isinstance(rows, dict) else []:
            if not isinstance(key, str) or not isinstance(raw, dict):
                continue
            last, deadline = _number(raw.get("last")), _number(raw.get("deadline"))
            if (
                last is None
                or deadline is None
                or not last
                <= wall
                < deadline
                <= last + BLUETOOTH_MATCHED_SOURCE_TIMEOUT
            ):
                continue
            source = registry.async_get(key)
            source_id = (
                next(
                    (
                        identity
                        for domain, identity in source.identifiers
                        if domain == DOMAIN
                    ),
                    None,
                )
                if source and source.config_entry_id == self.entry.entry_id
                else None
            )
            if source_id is None:
                deadline = min(deadline, last + BLUETOOTH_UNMATCHED_SOURCE_TIMEOUT)
            if deadline <= wall:
                continue
            self.sources[key] = SourceEvidence(
                key, source_id, now + last - wall, now + deadline - wall, last, deadline
            )
        self._load_trackers(data.get("trackers", {}), now, wall)

    def _load_trackers(self, rows: object, now: float, wall: float) -> None:
        """Validate tracker decisions separately from source leases."""
        for key, raw in rows.items() if isinstance(rows, dict) else []:
            if (
                key not in self._identities
                or key in self._invalidated
                or not isinstance(raw, dict)
            ):
                continue
            confirmed, expires = (
                _number(raw.get("confirmed")),
                _number(raw.get("expires")),
            )
            sighted = _number(raw.get("sighted"))
            state = raw.get("state")
            revision = raw.get("revision")
            if not isinstance(revision, str) or not revision:
                continue
            if confirmed is None or expires is None:
                continue
            if (
                not confirmed <= wall < expires
                or expires != confirmed + BLUETOOTH_CONFIRMATION_LEASE
                or state not in {"home", "not_home"}
            ):
                continue
            if (
                raw.get("sighted") is not None
                and (sighted is None or sighted > confirmed)
            ) or (state == "home" and sighted is None):
                continue
            self._revisions[key] = revision
            self.trackers[key] = PresenceEvidence(
                str(state),
                now + sighted - wall if sighted is not None else None,
                now + confirmed - wall,
                now + expires - wall,
                sighted,
                confirmed,
                expires,
                "restored",
                revision,
            )

    def check_clock(self, now: float) -> bool:
        """Reject a running-process wall/monotonic discontinuity conservatively."""
        offset = utc_timestamp() - now
        valid = self._offset is None or abs(offset - self._offset) <= 5
        self._offset = offset
        if not valid:
            self.trackers.clear()
            self.sources.clear()
            self.generation += 1
            self._remove_pending = True
            self.schedule_save()
        return valid

    def promote_bindings(self) -> None:
        """Persist newly available exact registry bindings without renewing age."""
        registry = dr.async_get(self.hass)
        for old_key, row in list(self.sources.items()):
            if row.source_id is None:
                continue
            registered = registry.async_get_device_by_identifier(
                (DOMAIN, row.source_id), self.entry.entry_id
            )
            if (
                registered is None
                or registered.id == old_key
                or registered.id in self.sources
            ):
                continue
            del self.sources[old_key]
            row.row_id = registered.id
            self.sources[row.row_id] = row
            self.schedule_save()

    def invalidate_restore(self) -> None:
        """Known coordinator failure closes eligibility without renewing evidence."""
        if self.trackers:
            self._invalidated.update(self.trackers)
            self.trackers.clear()
            self._remove_pending = True
            self.schedule_save()

    def source_reply(self, source_id: str, now: float) -> SourceEvidence:
        """Record only an accepted owned scan, retaining exact memory identity."""
        self.promote_bindings()
        row = next(
            (item for item in self.sources.values() if item.source_id == source_id),
            None,
        )
        if row is None:
            registered = dr.async_get(self.hass).async_get_device_by_identifier(
                (DOMAIN, source_id), self.entry.entry_id
            )
            row_id = registered.id if registered is not None else uuid4().hex
            row = self.sources[row_id] = SourceEvidence(
                row_id, source_id, now, now, 0, 0
            )
        wall = utc_timestamp()
        row.last_success, row.deadline = now, now + BLUETOOTH_MATCHED_SOURCE_TIMEOUT
        row.last_success_utc, row.deadline_utc = (
            wall,
            wall + BLUETOOTH_MATCHED_SOURCE_TIMEOUT,
        )
        self.schedule_save()
        return row

    def confirm(
        self,
        key: str,
        state: str,
        sighted: float | None,
        now: float,
        provenance: str,
        sighted_utc: float | None = None,
    ) -> None:
        """Store a real decision; saving itself never calls this method."""
        wall = utc_timestamp()
        self.trackers[key] = PresenceEvidence(
            state,
            sighted,
            now,
            now + BLUETOOTH_CONFIRMATION_LEASE,
            sighted_utc,
            wall,
            wall + BLUETOOTH_CONFIRMATION_LEASE,
            provenance,
            self._revisions.setdefault(key, uuid4().hex),
        )
        self._invalidated.discard(key)
        self.schedule_save()

    def snapshot(self) -> dict[str, object]:
        """Project an allowlisted latest snapshot, with no source/radio identity."""
        return {
            "policy": 1,
            "sources": {
                key: {"last": row.last_success_utc, "deadline": row.deadline_utc}
                for key, row in self.sources.items()
            },
            "trackers": {
                key: {
                    "revision": row.config_revision,
                    "state": row.state,
                    "sighted": row.sighted_utc,
                    "confirmed": row.confirmed_utc,
                    "expires": row.expires_utc,
                }
                for key, row in self.trackers.items()
                if key not in self._invalidated
            },
        }

    @callback
    def schedule_save(self) -> None:
        """Coalesce attempts without changing evidence or spawning parallel writers."""
        if self._save_cancel is None:
            self._save_cancel = self.hass.loop.call_later(_SAVE_DELAY, self._enqueue)

    @callback
    def _enqueue(self) -> None:
        if self._save_cancel is not None:
            self._save_cancel.cancel()
            self._save_cancel = None
        if not self._loaded or self._removed:
            return
        self._queue.append((self.generation, self._remove_pending, self.snapshot()))
        self._remove_pending = False
        if self._worker is None or self._worker.done():
            # Finite critical I/O must survive HA's initial cancellation of
            # background tasks. The STOP listener drains this same task/queue;
            # do not put it under an entry's cancellation or replace its owner.
            self._worker = self.hass.async_create_task(
                self._async_write(), "Save Bluetooth continuity", eager_start=False
            )

    async def _async_write(self) -> None:
        while self._queue:
            generation, remove, payload = self._queue.pop(0)
            if generation != self.generation:
                self._remove_pending |= remove
                continue
            remove |= self._remove_pending
            self._remove_pending = False
            if remove:
                try:
                    await self._store.async_remove()
                except OSError:
                    _LOGGER.warning(
                        "Could not remove Bluetooth continuity; memory stays invalidated"
                    )
            # This worker is domain-owned, never cancelled with an entry awaiter.
            # Same-generation queued evidence must also respect a later known
            # coordinator failure, whose restore tombstones do not stop retries.
            trackers = payload.get("trackers")
            if isinstance(trackers, dict):
                payload["trackers"] = {
                    key: row
                    for key, row in trackers.items()
                    if key not in self._invalidated
                }
            await self._store.async_save(payload)

    async def async_flush(self) -> None:
        """Wait on the same worker; cancellation does not cancel executor I/O."""
        self._enqueue()
        if self._worker is not None:
            await asyncio.shield(self._worker)

    async def _async_stop(self, _event: object) -> None:
        # Manual service callers can outlive interval-task cancellation too.
        self._scanner_instance = None
        await self.async_flush()

    async def async_remove(self) -> None:
        """Forget the removed entry after older in-flight operations finish."""
        self.generation += 1
        self.trackers.clear()
        self.sources.clear()
        self._remove_pending = True
        await self.async_flush()
        # No replacement file is required after removal.
        try:
            await self._store.async_remove()
        except OSError:
            _LOGGER.warning(
                "Could not remove Bluetooth continuity for the removed entry"
            )
        self._removed = True


@callback
def async_history(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> BluetoothHistory:
    """Install the early domain observer and return this entry's single owner."""
    if _HISTORY_KEY not in hass.data:
        histories: dict[str, BluetoothHistory] = {}
        hass.data[_HISTORY_KEY] = histories

        @callback
        def changed(
            _change: ConfigEntryChange, changed_entry: GoogleHomeConfigEntry
        ) -> None:
            if changed_entry.domain == DOMAIN:
                if changed_entry.entry_id not in histories:
                    histories[changed_entry.entry_id] = BluetoothHistory(
                        hass, changed_entry
                    )
                histories[changed_entry.entry_id].observe()

        async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, changed)
    histories = cast(dict[str, BluetoothHistory], hass.data[_HISTORY_KEY])
    if entry.entry_id not in histories:
        histories[entry.entry_id] = BluetoothHistory(hass, entry)
    histories[entry.entry_id].observe()
    return histories[entry.entry_id]
