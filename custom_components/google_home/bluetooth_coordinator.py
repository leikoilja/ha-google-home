"""Bluetooth polling plus evidence expiry independent of the polling schedule."""

import asyncio
from datetime import timedelta
import logging
from typing import override

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .bluetooth import (
    BluetoothScanner,
    DepartureToken,
    TrackerState,
    TrackerUpdate,
    bluetooth_now,
)
from .bluetooth_storage import BluetoothHistory
from .const import BLUETOOTH_SCAN_INTERVAL, DOMAIN
from .types import GoogleHomeConfigEntry

_LOGGER = logging.getLogger(__name__)


class BluetoothCoordinator(DataUpdateCoordinator[dict[str, TrackerUpdate]]):
    """Publish expiry without turning a failed coordinator into a healthy one."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoogleHomeConfigEntry,
        scanner: BluetoothScanner,
        history: BluetoothHistory,
    ) -> None:
        """Seed eligible state before entities are added, then schedule expiry."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_bluetooth",
            update_interval=timedelta(seconds=BLUETOOTH_SCAN_INTERVAL),
        )
        self.scanner = scanner
        self.history = history
        self._expiry: asyncio.TimerHandle | None = None
        self._departures: dict[
            str, tuple[DepartureToken, int, asyncio.TimerHandle]
        ] = {}
        self._stopped = False
        # First entity state uses eligible evidence, without waiting for a scan.
        self.data = scanner.evaluate()
        self._schedule_expiry()
        entry.async_on_unload(self.stop)
        client = entry.runtime_data.client
        client.bluetooth_graph_answered = self.graph_changed
        entry.async_on_unload(lambda: setattr(client, "bluetooth_graph_answered", None))

    def _check_clock(self) -> None:
        if not self.history.check_clock(bluetooth_now()):
            self.scanner.reset_clock()

    @override
    async def _async_update_data(self) -> dict[str, TrackerUpdate]:
        if not self.scanner.current():
            return self.data
        self._check_clock()
        result = await self.scanner.async_update()
        if not self.scanner.current():
            return self.data
        self._schedule_expiry()
        return result

    @callback
    @override
    def async_update_listeners(self) -> None:
        """Known coordinator failure cannot become an eligible restore snapshot."""
        if self._stopped or not self.scanner.current():
            return
        if not self.last_update_success:
            self.history.invalidate_restore()
        super().async_update_listeners()

    @callback
    def graph_changed(self) -> None:
        """Apply successful graph removal before a concurrent old reply can land."""
        if not self._stopped and self.scanner.current():
            self.data = self.scanner.evaluate(
                healthy=self.last_update_success
                and not self.history.entry.pref_disable_polling
            )
            self.async_update_listeners()
            self._schedule_expiry()

    @callback
    def _expire(self) -> None:
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if self._stopped or not self.scanner.current():
            return
        self._check_clock()
        # Do not use async_set_updated_data: it would reset coordinator failure.
        assert self.config_entry is not None
        healthy = (
            self.last_update_success and not self.config_entry.pref_disable_polling
        )
        self.data = self.scanner.evaluate(
            healthy=healthy, departures=self._due_departures()
        )
        self.async_update_listeners()
        self._schedule_expiry()

    @callback
    def update_departure_delays(self) -> None:
        """Apply config inline while HA invokes its single existing listener."""
        if (
            not self._stopped
            and self.scanner.current()
            and self.scanner.sync_departure_delays()
        ):
            self._schedule_departures()

    def _due_departures(self) -> dict[str, DepartureToken]:
        self.scanner.sync_departure_delays()
        now = bluetooth_now()
        return {
            device.subentry_id: token
            for device in self.scanner.tracked
            if (pending := self._departures.get(device.subentry_id)) is not None
            for token, generation, _handle in [pending]
            if device.pending_departure == token
            and generation == self.scanner.generation
            and token.deadline <= now
        }

    @callback
    def _depart(self, subentry_id: str, token: DepartureToken, generation: int) -> None:
        if self._stopped or not self.scanner.current():
            return
        self.update_departure_delays()
        pending = self._departures.get(subentry_id)
        if (
            pending is None
            or pending[:2] != (token, generation)
            or generation != self.scanner.generation
        ):
            return
        if bluetooth_now() < token.deadline:
            # asyncio may invoke timers a clock-resolution tick early.
            pending[2].cancel()
            del self._departures[subentry_id]
            self._schedule_departures()
            return
        self._expire()

    @callback
    def _schedule_departures(self) -> None:
        pending = {
            device.subentry_id: device.pending_departure
            for device in self.scanner.tracked
            if device.pending_departure is not None
        }
        for key, (token, generation, handle) in list(self._departures.items()):
            if (
                pending.get(key) != token
                or generation != self.scanner.generation
                or self._stopped
            ):
                handle.cancel()
                del self._departures[key]
        if self._stopped:
            return
        for key, token in pending.items():
            if key not in self._departures:
                generation = self.scanner.generation
                self._departures[key] = (
                    token,
                    generation,
                    self.hass.loop.call_later(
                        max(0, token.deadline - bluetooth_now()),
                        self._depart,
                        key,
                        token,
                        generation,
                    ),
                )

    @callback
    def _schedule_expiry(self) -> None:
        self._schedule_departures()
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if not self._stopped and (deadlines := self.scanner.deadlines()):
            self._expiry = self.hass.loop.call_later(
                max(0, min(deadlines) - bluetooth_now()), self._expire
            )

    @callback
    def stop(self) -> None:
        """Cancel entry timers without cancelling the domain Store worker."""
        if self._stopped:
            return
        self._stopped = True
        self.scanner.retire()
        self._schedule_departures()
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        # A failed platform unload can leave entities attached. Publish lifecycle
        # unavailability once, without treating retirement as failed evidence or
        # erasing the original, still-eligible restoration lease.
        self.data = {
            key: TrackerUpdate(TrackerState.UNAVAILABLE, {}) for key in self.data
        }
        super().async_update_listeners()
