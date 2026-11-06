"""Bluetooth presence tracking with the Bluetooth scans of Google Home devices.

Each update reads the results of the scan that every speaker started in the
previous update, then starts the next scan. A tracked device is home while a
speaker heard it recently. Away requires continuous coverage from every
required speaker, and at least one active scanner. None may have heard the
device within the presence window. A silent source expires after five minutes;
an unidentifiable saved source expires sooner, from its original reply age.
Meanwhile the tracker keeps its last state for a few minutes, so a missed scan
doesn't make it flap. A device that never returned results, such as a TV that
refuses the connection instead of answering 404, can't keep trackers from
showing away.

Each tracker also shows how strongly each speaker heard the device: the median
over windows of a few minutes, as single readings swing by about 20 dB even
when the device lies still. A window covers only time in one state, so it
restarts whenever the tracker's state changes.
"""

import asyncio
import base64
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from http import HTTPStatus
import logging
import re
from statistics import median
from time import monotonic
from typing import Literal, cast

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp.client_exceptions import ContentTypeError
from bluetooth_data_tools import get_cipher_for_irk, resolve_private_address

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MAC
from homeassistant.util import dt as dt_util

from . import bluetooth_storage
from .bluetooth_storage import BluetoothHistory, SourceEvidence
from .const import (
    API_ENDPOINT_BLUETOOTH_RESULTS,
    API_ENDPOINT_BLUETOOTH_SCAN,
    BLUETOOTH_CONFIRMATION_LEASE,
    BLUETOOTH_MATCHED_SOURCE_TIMEOUT,
    BLUETOOTH_MAX_RESULT_AGE,
    BLUETOOTH_MAX_SCAN_GAP,
    BLUETOOTH_MIN_RSSI,
    BLUETOOTH_PRESENCE_WINDOW,
    BLUETOOTH_RSSI_MIN_SCANS,
    BLUETOOTH_RSSI_WINDOW,
    BLUETOOTH_SCAN_INTERVAL,
    BLUETOOTH_TIMEOUT,
    CONF_ADDITIONAL_DEPARTURE_DELAY,
    CONF_IRK,
    DEPARTURE_DELAY_VALUES,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    PORT,
)
from .coordinator import GoogleAccountCoordinator, async_device_disabled
from .device_info import create_url
from .models import GoogleHomeDevice
from .types import BluetoothJsonDict, JsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)

IRK_LENGTH = 16


class BluetoothScanError(Exception):
    """Error to indicate a device didn't start a Bluetooth scan or return its results."""


class BluetoothScanUnsupported(BluetoothScanError):
    """Error to indicate a device has no Bluetooth scan endpoint."""


async def async_start_bluetooth_scan(
    session: ClientSession, device: GoogleHomeDevice
) -> None:
    """Start a Bluetooth scan that clears the results of the previous one.

    The speaker scans for up to one update interval, then stops on its own, also
    after the integration unloads. The next Bluetooth update reads the results.
    """
    await _async_bluetooth_request(
        session,
        "POST",
        API_ENDPOINT_BLUETOOTH_SCAN,
        device,
        {"enable": True, "clear_results": True, "timeout": BLUETOOTH_SCAN_INTERVAL},
    )


async def async_get_bluetooth_scan_results(
    session: ClientSession, device: GoogleHomeDevice
) -> list[BluetoothJsonDict]:
    """Return the Bluetooth devices the device heard since its scan started."""
    response = await _async_bluetooth_request(
        session, "GET", API_ENDPOINT_BLUETOOTH_RESULTS, device
    )
    if not isinstance(response, list):
        raise BluetoothScanError(f"{device.name} returned no list of results")
    return [
        {"mac_address": result["mac_address"], "rssi": result["rssi"]}
        for result in cast(list[object], response)
        if isinstance(result, dict)
        and isinstance(result.get("mac_address"), str)
        and isinstance(result.get("rssi"), int)
    ]


async def _async_bluetooth_request(
    session: ClientSession,
    method: Literal["GET", "POST"],
    endpoint: str,
    device: GoogleHomeDevice,
    data: JsonDict | None = None,
) -> object:
    """Send a Bluetooth request and return its JSON response.

    Unlike the client's requests, a failure leaves the device's availability alone
    and raises instead of logging, as Bluetooth updates run every 30 seconds. The
    device has less time to answer than the client's requests give it, so that scan
    results are read while they're fresh enough to use.
    """
    if not device.ip_address or not device.auth_token:
        raise BluetoothScanError(f"{device.name} has no IP address or auth token")
    url = create_url(device.ip_address, PORT, endpoint)
    headers = {
        HEADER_CAST_LOCAL_AUTH: device.auth_token,
        HEADER_CONTENT_TYPE: "application/json",
    }
    try:
        async with session.request(
            method,
            url,
            json=data,
            headers=headers,
            timeout=ClientTimeout(total=BLUETOOTH_TIMEOUT),
        ) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                raise BluetoothScanUnsupported(f"{device.name} returned 404")
            if response.status != HTTPStatus.OK:
                raise BluetoothScanError(f"{device.name} returned {response.status}")
            try:
                return cast(object, await response.json())
            except ContentTypeError:
                return None
    except (ClientError, TimeoutError, ValueError) as err:
        raise BluetoothScanError(f"{device.name} didn't answer: {err!r}") from err


def bluetooth_now() -> float:
    """Use the scanner clock for setup, expiry and accepted replies alike."""
    return monotonic()


class TrackerState(StrEnum):
    """State of a tracked Bluetooth device."""

    HOME = "home"
    NOT_HOME = "not_home"
    # Nothing is known yet since setup
    UNKNOWN = "unknown"
    # Was known, but the speakers can't tell any more
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TrackerUpdate:
    """State of a tracked device after an update, and the speakers that hear it."""

    state: TrackerState
    # Median RSSI in dBm of each speaker over the latest completed window, by
    # speaker name, strongest first
    speakers: dict[str, int]


def parse_irk(value: str) -> bytes | None:
    """Return the IRK in a format Home Assistant's Private BLE Device accepts.

    That is hex, or base64 as macOS Keychain shows it, which is in reverse byte
    order. Returns None for anything that isn't 16 bytes.
    """
    value = value.strip().removeprefix("irk:")
    try:
        if value.endswith("="):
            irk = base64.b64decode(value, validate=True)[::-1]
        else:
            irk = bytes.fromhex(re.sub(r"[\s:-]", "", value.removeprefix("0x")))
    except ValueError:
        return None
    return irk if len(irk) == IRK_LENGTH else None


def normalize_mac(value: str) -> str | None:
    """Return a MAC address as AA:BB:CC:DD:EE:FF, or None if it isn't one."""
    digits = re.sub(r"[\s:.-]", "", value)
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).upper()


def parse_mac(value: str) -> str | None:
    """Return a MAC address written as six hex pairs, as AA:BB:CC:DD:EE:FF.

    The pairs are separated all by colons or all by hyphens. Returns None for
    anything else.
    """
    if not re.fullmatch(
        r"[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}", value
    ):
        return None
    return value.replace("-", ":").upper()


@dataclass(frozen=True)
class DepartureToken:
    """A single pending transition, not persisted absence evidence."""

    policy_generation: int
    sighted: float
    deadline: float


def configured_departure_delay(subentry: ConfigSubentry) -> int:
    """Missing or invalid legacy metadata leaves the normal timing in place."""
    value = subentry.data.get(CONF_ADDITIONAL_DEPARTURE_DELAY, 0)
    if (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and value in DEPARTURE_DELAY_VALUES
    ):
        return int(value)
    return 0


class TrackedDevice:
    """A Bluetooth device that the user tracks, identified by its IRK or MAC address."""

    def __init__(self, subentry: ConfigSubentry) -> None:
        """Create a tracked device from its subentry."""
        self.subentry_id = subentry.subentry_id
        irk: str | None = subentry.data.get(CONF_IRK)
        # The subentry flow saves the IRK as hex, in the order the cipher takes
        self._cipher = get_cipher_for_irk(bytes.fromhex(irk)) if irk else None
        self._mac: str | None = subentry.data.get(CONF_MAC)
        self.identity = (irk, self._mac)
        self.departure_delay = configured_departure_delay(subentry)
        self.policy_generation = 0
        self.pending_departure: DepartureToken | None = None
        # Start of the latest scan that heard the device
        self.last_sighted: float | None = None
        # The latest home or away state, and when the speakers last confirmed it
        self.state = TrackerState.UNKNOWN
        self.confirmed_at: float | None = None
        self.confirmed_now = False
        self.last_sighted_utc: float | None = None
        self.live_sighting = False
        self.provenance = "live"
        # The strongest RSSI each speaker heard the device at in this update,
        # by the speaker's device ID
        self.heard: dict[str, int] = {}
        # The state of the latest update, and the window of RSSI readings by
        # device ID since it started or the last window completed
        self.shown_state: TrackerState | None = None
        self.window_start = 0.0
        self.readings: dict[str, list[int]] = {}
        self.speakers: dict[str, int] = {}

    def matches(self, address: str) -> bool:
        """Return whether a normalized address is this device's."""
        if self._cipher is not None:
            # Returns False for addresses that aren't resolvable private ones
            return resolve_private_address(self._cipher, address)
        return address == self._mac


@dataclass
class SpeakerScan:
    """Bluetooth scan state of one speaker. Times are monotonic, in seconds."""

    name: str
    ip_address: str | None
    auth_token: str | None
    # Start of the scan that this speaker started and that wasn't read yet
    pending_start: float | None = None
    # Start of the unbroken run of read scans; None while broken
    run_start: float | None = None
    # End of what the latest read scan covered
    covered_until: float | None = None
    # When the speaker started keeping trackers from showing away
    uncovered_since: float | None = None
    warned: bool = False

    def covers(self, now: float) -> bool:
        """Return whether the speaker scanned without a break for the whole window."""
        return (
            self.run_start is not None
            and self.covered_until is not None
            and self.run_start <= now - BLUETOOTH_PRESENCE_WINDOW
            and self.covered_until
            >= now - BLUETOOTH_SCAN_INTERVAL - BLUETOOTH_MAX_SCAN_GAP
        )


class BluetoothScanner:
    """Scan with the speakers and work out whether each tracked device is home."""

    def __init__(
        self,
        session: ClientSession,
        account: GoogleAccountCoordinator,
        subentries: Iterable[ConfigSubentry],
        excluded: Iterable[str],
        history: BluetoothHistory | None = None,
    ) -> None:
        """Create a scanner for the tracked devices, using the devices Google lists."""
        self._history = history
        self._instance = history.claim_scanner() if history else object()
        self._retired = False
        self._generation = history.generation if history else 0
        self._leases = history.sources if history else {}
        self._membership_changed = False
        self._accepted = False
        self._session = session
        self._account = account
        self.tracked = [TrackedDevice(subentry) for subentry in subentries]
        self._excluded = set(excluded)
        # Speakers that scan, by device ID
        self._speakers: dict[str, SpeakerScan] = {}
        self._unsupported: set[str] = set()
        # Diagnostic history survives a speaker becoming unsupported or disabled.
        self._answered: set[str] = set()
        if history is not None:
            now = monotonic()
            for device in self.tracked:
                row = history.trackers.get(device.subentry_id)
                if row is not None and now < row.expires:
                    device.state = TrackerState(row.state)
                    device.last_sighted = row.sighted
                    device.last_sighted_utc = row.sighted_utc
                    device.confirmed_at = row.confirmed
                    device.provenance = "restored"

        self._updates = {
            device.subentry_id: TrackerUpdate(device.state, {})
            for device in self.tracked
        }

    def retire(self) -> None:
        """Close this setup before unload awaits, without changing saved evidence."""
        self._retired = True
        if self._history:
            self._history.retire_scanner(self._instance)

    def reset_clock(self) -> None:
        """Start fresh after a detected clock discontinuity, retaining identities."""
        assert self._history is not None
        self._generation = self._history.generation
        for speaker in self._speakers.values():
            speaker.run_start = speaker.covered_until = speaker.pending_start = None
        for device in self.tracked:
            device.last_sighted = device.confirmed_at = device.last_sighted_utc = None
            device.state = TrackerState.UNKNOWN
            device.live_sighting = False
            device.pending_departure = None
            device.policy_generation += 1

    def current(self) -> bool:
        """An obsolete scanner must not apply late replies or timer decisions."""
        return not self._retired and (
            self._history is None
            or (
                self._history.owns_scanner(self._instance)
                and self._generation == self._history.generation
            )
        )

    @property
    def generation(self) -> int:
        """Expose the current scanner epoch for queued callback ownership."""
        return self._generation

    def sync_departure_delays(self) -> bool:
        """Reconcile current non-identity policy without touching evidence."""
        if self._history is None:
            return False
        changed = False
        for subentry in self._history.entry.get_subentries_of_type("bluetooth_device"):
            for device in self.tracked:
                if device.subentry_id == subentry.subentry_id and device.identity == (
                    subentry.data.get(CONF_IRK),
                    subentry.data.get(CONF_MAC),
                ):
                    changed |= self.update_departure_delay(
                        device, configured_departure_delay(subentry)
                    )
        return changed

    @staticmethod
    def update_departure_delay(device: TrackedDevice, seconds: int) -> bool:
        """Change one runtime policy/token, never a history or scanner epoch."""
        if device.departure_delay == seconds:
            return False
        device.departure_delay = seconds
        device.policy_generation += 1
        if device.pending_departure is not None:
            sighted = device.pending_departure.sighted
            device.pending_departure = DepartureToken(
                device.policy_generation,
                sighted,
                sighted + BLUETOOTH_PRESENCE_WINDOW + seconds,
            )
        return True

    def _eligible(self, source_id: str) -> bool:
        account = self._account
        roster = getattr(account.client, "bluetooth_source_ids", None)
        return (
            self.current()
            and source_id not in self._excluded
            and source_id not in self._unsupported
            and (not isinstance(roster, set) or source_id in roster)
            and not async_device_disabled(account.hass, account.config_entry, source_id)
        )

    def _expire_sources(self, now: float) -> bool:
        expired = False
        for key, row in list(self._leases.items()):
            if row.deadline <= now:
                del self._leases[key]
                if row.source_id in self._speakers:
                    speaker = self._speakers[row.source_id]
                    speaker.run_start = speaker.covered_until = None
                expired = True
        if expired and self._history:
            self._history.schedule_save()
        self._membership_changed |= expired
        return expired

    def evaluate(
        self,
        *,
        healthy: bool = True,
        scan: bool = False,
        departures: Mapping[str, DepartureToken] | None = None,
    ) -> dict[str, TrackerUpdate]:
        """One owner decides at actual time, processing source D before tracker E."""
        if not self.current():
            return self._updates
        self.sync_departure_delays()
        now = monotonic()
        self._expire_sources(now)
        self._update_speakers()
        required = [
            self._speakers.get(row.source_id or "") for row in self._leases.values()
        ]
        covered = (
            healthy
            and bool(required)
            and all(speaker is not None and speaker.covers(now) for speaker in required)
        )
        self._warn_about_blocking_speakers(
            [speaker for speaker in required if speaker is not None], now
        )
        decision = healthy and ((scan and self._accepted) or self._membership_changed)
        provenance = "live" if scan and self._accepted else "membership_expiry"
        self._membership_changed = False
        updates = {}
        for device in self.tracked:
            token = (departures or {}).get(device.subentry_id)
            delayed = (
                token is not None
                and token == device.pending_departure
                and self.current()
                and now >= token.deadline
            )
            if delayed:
                device.pending_departure = None
            state = self._state(
                device,
                now,
                covered,
                confirm=decision or (healthy and delayed),
                home_confirm=scan and self._accepted and device.live_sighting,
            )
            if device.confirmed_now and self._history:
                device.provenance = "departure_delay" if delayed else provenance
                self._history.confirm(
                    device.subentry_id,
                    str(device.state),
                    device.last_sighted,
                    now,
                    device.provenance,
                    device.last_sighted_utc,
                )
            updates[device.subentry_id] = self._tracker_update(device, state, now)
            device.heard = {}
        self._updates = updates
        return updates

    def deadlines(self) -> list[float]:
        """Return only future deadlines; consumed expiry events cannot renew state."""
        if not self.current():
            return []
        now = monotonic()
        return [row.deadline for row in self._leases.values() if row.deadline > now] + [
            device.confirmed_at + BLUETOOTH_CONFIRMATION_LEASE
            for device in self.tracked
            if device.confirmed_at is not None
            and device.confirmed_at + BLUETOOTH_CONFIRMATION_LEASE > now
        ]

    def diagnostics(self) -> dict[str, object]:
        """Return only speaker scan facts, without credentials or scan contents.

        Coverage is evaluated at download time. Its endpoint is the end of the
        covered scan interval, not when results were read. Convert the monotonic
        endpoint to a wall-clock timestamp using the clocks at download time.
        """
        now = monotonic()
        wall_now = dt_util.utcnow()
        speakers: dict[str, object] = {}
        for device_id in self._account.data or {}:
            excluded = device_id in self._excluded or async_device_disabled(
                self._account.hass, self._account.config_entry, device_id
            )
            speaker = self._speakers.get(device_id) if not excluded else None
            covered_until = speaker.covered_until if speaker is not None else None
            lease = next(
                (row for row in self._leases.values() if row.source_id == device_id),
                None,
            )
            participating = (
                lease is not None
                and now < lease.deadline
                and not excluded
                and device_id not in self._unsupported
            )
            speakers[device_id] = {
                "participating": participating,
                "last_success_age": round(max(0, now - lease.last_success), 1)
                if lease is not None
                else None,
                "remaining_lease": round(max(0, lease.deadline - now), 1)
                if lease is not None
                else None,
                "excluded": excluded,
                "unsupported": device_id in self._unsupported,
                "answered": device_id in self._answered,
                "covers_presence_window": speaker.covers(now) if speaker else False,
                "covered_until": (
                    dt_util.as_local(
                        wall_now + timedelta(seconds=covered_until - now)
                    ).isoformat()
                    if covered_until is not None
                    else None
                ),
            }
        return speakers

    async def async_update(self) -> dict[str, TrackerUpdate]:
        """Read the scans of the previous update, start new ones, and return the updates."""
        if not self.current():
            return self._updates
        generation = self._generation
        self._expire_sources(monotonic())
        self._accepted = False
        devices = self._update_speakers()
        for device in self.tracked:
            device.heard = {}
        tasks = [
            asyncio.create_task(
                self._async_update_speaker(device_id, speaker, devices[device_id])
            )
            for device_id, speaker in list(self._speakers.items())
            if device_id in devices
        ]
        try:
            await asyncio.gather(*tasks)
        except Exception, asyncio.CancelledError:
            # A failed coordinator cannot leave sibling requests mutating history.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            caller = asyncio.current_task()
            if (not self.current() or generation != self._generation) and not (
                caller is not None and caller.cancelling()
            ):
                return self._updates
            raise
        if not self.current() or generation != self._generation:
            return self._updates
        return self.evaluate(scan=True)

    def _update_speakers(self) -> dict[str, GoogleHomeDevice]:
        """Update the speakers that scan from Google's device list.

        A speaker starts scanning once it has an address and a token. Once it
        has returned scan results, it keeps counting while Google lists it, even
        if it stops answering. It keeps the name Google lists it by, also after
        a rename. A speaker that is disabled in Home Assistant doesn't scan or
        count until it's enabled again.
        """
        account = self._account
        if self._history:
            self._history.promote_bindings()
        devices = {
            device_id: device
            for device_id, device in (account.data or {}).items()
            if not async_device_disabled(account.hass, account.config_entry, device_id)
        }
        for key, row in list(self._leases.items()):
            if row.source_id is not None and not self._eligible(row.source_id):
                del self._leases[key]
                if self._history:
                    self._history.schedule_save()
        for device_id in list(self._speakers):
            if device_id not in devices or not self._eligible(device_id):
                del self._speakers[device_id]
        for device_id, device in devices.items():
            if not self._eligible(device_id):
                continue
            speaker = self._speakers.get(device_id)
            if speaker is None:
                if device.ip_address and device.auth_token:
                    self._speakers[device_id] = SpeakerScan(
                        device.name, device.ip_address, device.auth_token
                    )
                continue
            speaker.name = device.name
            if (speaker.ip_address, speaker.auth_token) != (
                device.ip_address,
                device.auth_token,
            ):
                # A scan started at the old address or with the old token is
                # unknown to this one
                speaker.ip_address = device.ip_address
                speaker.auth_token = device.auth_token
                speaker.pending_start = None
                speaker.run_start = None
        return devices

    async def _async_update_speaker(
        self, device_id: str, speaker: SpeakerScan, device: GoogleHomeDevice
    ) -> None:
        """Read the speaker's pending scan, if any, then start the next one."""
        epoch = self._generation
        endpoint = (speaker.ip_address, speaker.auth_token)

        def owns_request() -> bool:
            if (
                epoch != self._generation
                or not self._eligible(device_id)
                or self._speakers.get(device_id) is not speaker
            ):
                return False
            current_device = (self._account.data or {}).get(device_id)
            if (
                current_device is None
                or (current_device.ip_address, current_device.auth_token) != endpoint
                or (device.ip_address, device.auth_token) != endpoint
            ):
                self._update_speakers()
                return False
            return True

        if not owns_request():
            return
        start, speaker.pending_start = speaker.pending_start, None
        if start is None:
            # Nothing to read: the first update, or starting the scan failed
            speaker.run_start = None
        elif not await self._async_read_pending(
            device_id, speaker, device, start, owns_request
        ):
            return
        if not owns_request():
            return
        start = monotonic()
        try:
            await async_start_bluetooth_scan(self._session, device)
        except BluetoothScanUnsupported:
            if owns_request():
                self._mark_unsupported(device_id, speaker)
        except BluetoothScanError as err:
            if not owns_request():
                return
            # It may have cleared the results or not, so they're never read
            _LOGGER.debug("Failed to start Bluetooth scan: %s", err)
        else:
            if owns_request():
                speaker.pending_start = start

    async def _async_read_pending(
        self,
        device_id: str,
        speaker: SpeakerScan,
        device: GoogleHomeDevice,
        start: float,
        owns_request: Callable[[], bool],
    ) -> bool:
        """Apply a completed read/error only while this request still owns it."""
        try:
            results = await async_get_bluetooth_scan_results(self._session, device)
        except BluetoothScanUnsupported:
            if owns_request():
                self._mark_unsupported(device_id, speaker)
            return False
        except BluetoothScanError as err:
            if not owns_request():
                return False
            _LOGGER.debug("Failed to read Bluetooth scan: %s", err)
            speaker.run_start = None
        else:
            if not owns_request():
                return False
            self._read_scan(device_id, speaker, start, results)
        return True

    def _read_scan(
        self,
        device_id: str,
        speaker: SpeakerScan,
        start: float,
        results: list[BluetoothJsonDict],
    ) -> None:
        """Record the sightings of a scan that started at start, if it's recent."""
        read = monotonic()
        if read - start > BLUETOOTH_MAX_RESULT_AGE:
            _LOGGER.debug(
                "Discarded Bluetooth scan of %s read %.0f seconds after it started",
                speaker.name,
                read - start,
            )
            speaker.run_start = None
            return
        self._expire_sources(read)
        self._accepted = True
        self._answered.add(device_id)
        if self._history:
            self._history.source_reply(device_id, read)
        else:
            wall = bluetooth_storage.utc_timestamp()
            self._leases[device_id] = SourceEvidence(
                device_id,
                device_id,
                read,
                read + BLUETOOTH_MATCHED_SOURCE_TIMEOUT,
                wall,
                wall + BLUETOOTH_MATCHED_SOURCE_TIMEOUT,
            )
        # Only counts: the results include the neighbours' devices
        _LOGGER.debug("%s heard %d Bluetooth devices", speaker.name, len(results))
        for result in results:
            if result["rssi"] < BLUETOOTH_MIN_RSSI:
                continue
            address = normalize_mac(result["mac_address"])
            if address is None:
                continue
            for device in self.tracked:
                if not device.matches(address):
                    continue
                device.pending_departure = None
                if device.last_sighted is None or device.last_sighted < start:
                    # The scan's start, as the device may have been heard then
                    device.last_sighted = start
                    device.last_sighted_utc = (
                        bluetooth_storage.utc_timestamp() + start - read
                    )
                device.live_sighting = True
                # One reading per scan, even if it heard several of the
                # device's addresses
                device.heard[device_id] = max(
                    result["rssi"], device.heard.get(device_id, result["rssi"])
                )
        if (
            speaker.run_start is None
            or speaker.covered_until is None
            or start > speaker.covered_until + BLUETOOTH_MAX_SCAN_GAP
        ):
            speaker.run_start = start
        speaker.covered_until = min(read, start + BLUETOOTH_SCAN_INTERVAL)

    def _mark_unsupported(self, device_id: str, speaker: SpeakerScan) -> None:
        """Stop scanning with a speaker that has no Bluetooth scan endpoint."""
        if not self.current() or self._speakers.get(device_id) is not speaker:
            return
        _LOGGER.debug(
            "%s doesn't support Bluetooth scans, not using it until reload",
            speaker.name,
        )
        self._unsupported.add(device_id)
        self._speakers.pop(device_id, None)
        for key, row in list(self._leases.items()):
            if row.source_id == device_id:
                del self._leases[key]
        if self._history:
            self._history.schedule_save()

    @staticmethod
    def _warn_about_blocking_speakers(answered: list[SpeakerScan], now: float) -> None:
        """Warn once about each speaker that keeps trackers from showing away."""
        for speaker in answered:
            if speaker.covers(now):
                speaker.uncovered_since = None
                speaker.warned = False
            elif speaker.uncovered_since is None:
                speaker.uncovered_since = now
            elif (
                not speaker.warned
                and now - speaker.uncovered_since >= BLUETOOTH_CONFIRMATION_LEASE
            ):
                speaker.warned = True
                _LOGGER.warning(
                    "%s has not provided continuous Bluetooth coverage for %d minutes, "
                    "so Bluetooth trackers cannot show away. If it is out of service, add it to "
                    "'Speakers not used for Bluetooth tracking' in the integration's "
                    "options",
                    speaker.name,
                    BLUETOOTH_CONFIRMATION_LEASE // 60,
                )

    @staticmethod
    def _state(
        device: TrackedDevice,
        now: float,
        covered: bool,
        *,
        confirm: bool = True,
        home_confirm: bool = True,
    ) -> TrackerState:
        """Confirm with new evidence; otherwise retain only the original lease."""
        device.confirmed_now = False
        home = (
            device.last_sighted is not None
            and device.last_sighted > now - BLUETOOTH_PRESENCE_WINDOW
        )
        if home:
            device.pending_departure = None
        delay_until = (
            device.last_sighted + BLUETOOTH_PRESENCE_WINDOW + device.departure_delay
            if device.last_sighted is not None
            else None
        )
        postponing = (
            device.state == TrackerState.HOME
            and device.confirmed_at is not None
            and now < device.confirmed_at + BLUETOOTH_CONFIRMATION_LEASE
            and delay_until is not None
            and now < delay_until
        )
        if confirm and home and home_confirm:
            device.state, device.confirmed_at = TrackerState.HOME, now
            device.confirmed_now = True
        elif confirm and not home and covered:
            if postponing:
                assert device.last_sighted is not None and delay_until is not None
                device.pending_departure = DepartureToken(
                    device.policy_generation, device.last_sighted, delay_until
                )
            else:
                device.pending_departure = None
                device.state, device.confirmed_at = TrackerState.NOT_HOME, now
                device.confirmed_now = True
        elif device.confirmed_at is None:
            return TrackerState.UNKNOWN
        elif now - device.confirmed_at >= BLUETOOTH_CONFIRMATION_LEASE:
            return TrackerState.UNAVAILABLE
        return device.state

    def _tracker_update(
        self, device: TrackedDevice, state: TrackerState, now: float
    ) -> TrackerUpdate:
        """Add the update's readings to the window and return the device's update.

        A state change starts a new window and empties the speakers, so a summary
        never mixes readings from before and after it, and away shows none. A
        completed window replaces the speakers, even with none that qualify.
        """
        if state != device.shown_state:
            device.shown_state, device.window_start = state, now
            device.readings, device.speakers = {}, {}
        for device_id, rssi in device.heard.items():
            device.readings.setdefault(device_id, []).append(rssi)
        if now - device.window_start >= BLUETOOTH_RSSI_WINDOW:
            # Each speaker counts on its own readings, if it still scans: not one
            # that Google stopped listing or that returned 404. Speakers with the
            # same name share an entry, with the strongest median.
            speakers: dict[str, int] = {}
            for device_id, readings in device.readings.items():
                if (
                    len(readings) >= BLUETOOTH_RSSI_MIN_SCANS
                    and (speaker := self._speakers.get(device_id)) is not None
                ):
                    rssi = round(median(readings))
                    speakers[speaker.name] = max(rssi, speakers.get(speaker.name, rssi))
            device.speakers = dict(
                sorted(speakers.items(), key=lambda item: (-item[1], item[0]))
            )
            device.window_start, device.readings = now, {}
        return TrackerUpdate(state, device.speakers)
