"""Bluetooth presence tracking with the Bluetooth scans of Google Home devices.

Each update reads the results of the scan that every speaker started in the
previous update, then starts the next scan. A tracked device is home while a
speaker heard it recently. It's away only when every speaker that has returned
scan results since setup has scanned without a break for the whole presence
window and none heard it: a speaker that stops answering can't confirm that a
device is gone. A device that never returned results, such as a TV that refuses
the connection instead of answering 404, can't keep trackers from showing away.
"""

import asyncio
import base64
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
import logging
import re
import time

from bluetooth_data_tools import get_cipher_for_irk, resolve_private_address

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MAC
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import (
    BLUETOOTH_BLOCKING_WARNING,
    BLUETOOTH_MAX_RESULT_AGE,
    BLUETOOTH_MAX_SCAN_GAP,
    BLUETOOTH_MIN_RSSI,
    BLUETOOTH_PRESENCE_WINDOW,
    BLUETOOTH_SCAN_INTERVAL,
    CONF_IRK,
)
from .exceptions import BluetoothScanError, BluetoothScanUnsupported
from .models import GoogleHomeDevice
from .types import BluetoothJsonDict

_LOGGER: logging.Logger = logging.getLogger(__package__)

IRK_LENGTH = 16


class TrackerState(StrEnum):
    """State of a tracked Bluetooth device."""

    HOME = "home"
    NOT_HOME = "not_home"
    # Nothing is known yet since setup
    UNKNOWN = "unknown"
    # Was known, but the speakers can't tell any more
    UNAVAILABLE = "unavailable"


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


class TrackedDevice:
    """A Bluetooth device that the user tracks, identified by its IRK or MAC address."""

    def __init__(self, subentry: ConfigSubentry) -> None:
        """Create a tracked device from its subentry."""
        self.subentry_id = subentry.subentry_id
        irk: str | None = subentry.data.get(CONF_IRK)
        # The subentry flow saves the IRK as hex, in the order the cipher takes
        self._cipher = get_cipher_for_irk(bytes.fromhex(irk)) if irk else None
        self._mac: str | None = subentry.data.get(CONF_MAC)
        # Start of the latest scan that heard the device
        self.last_sighted: float | None = None
        # Whether the device was home or away since setup
        self.state_known = False

    def matches(self, address: str) -> bool:
        """Return whether a normalized address is this device's."""
        if self._cipher is not None:
            # Returns False for addresses that aren't resolvable private ones
            return resolve_private_address(self._cipher, address)
        return address == self._mac


@dataclass
class SpeakerScan:
    """Bluetooth scan state of one speaker. Times come from the scanner's clock."""

    name: str
    ip_address: str | None
    auth_token: str | None
    # Start of the scan that this speaker started and that wasn't read yet
    pending_start: float | None = None
    # Start of the unbroken run of read scans; None while broken
    run_start: float | None = None
    # End of what the latest read scan covered
    covered_until: float | None = None
    # Whether it returned scan results since setup, so it supports scans
    answered: bool = False
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
        client: GlocaltokensApiClient,
        coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]],
        subentries: Iterable[ConfigSubentry],
        excluded: Iterable[str],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a scanner for the tracked devices, using the coordinator's speakers."""
        self._client = client
        self._coordinator = coordinator
        self.tracked = [TrackedDevice(subentry) for subentry in subentries]
        self._excluded = set(excluded)
        self._clock = clock
        # Speakers that scan, by device ID
        self._speakers: dict[str, SpeakerScan] = {}
        self._unsupported: set[str] = set()

    async def async_update(self) -> dict[str, TrackerState]:
        """Read the scans of the previous update, start new ones, and return the states."""
        devices = self._update_speakers()
        await asyncio.gather(
            *(
                self._async_update_speaker(device_id, speaker, devices[device_id])
                for device_id, speaker in list(self._speakers.items())
            )
        )
        now = self._clock()
        answered = [speaker for speaker in self._speakers.values() if speaker.answered]
        self._warn_about_blocking_speakers(answered, now)
        # No speaker to scan with can't confirm that a device is away
        covered = bool(answered) and all(speaker.covers(now) for speaker in answered)
        return {
            device.subentry_id: self._state(device, now, covered)
            for device in self.tracked
        }

    def _update_speakers(self) -> dict[str, GoogleHomeDevice]:
        """Update the speakers that scan from Google's device list.

        A speaker starts scanning once it has an address and a token. Once it
        has returned scan results, it keeps counting while Google lists it, even
        if it stops answering.
        """
        devices = {device.device_id: device for device in self._coordinator.data or []}
        for device_id in list(self._speakers):
            if device_id not in devices:
                del self._speakers[device_id]
        for device_id, device in devices.items():
            if device_id in self._excluded or device_id in self._unsupported:
                continue
            speaker = self._speakers.get(device_id)
            if speaker is None:
                if device.ip_address and device.auth_token:
                    self._speakers[device_id] = SpeakerScan(
                        device.name, device.ip_address, device.auth_token
                    )
            elif (speaker.ip_address, speaker.auth_token) != (
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
        start, speaker.pending_start = speaker.pending_start, None
        if start is None:
            # Nothing to read: the first update, or starting the scan failed
            speaker.run_start = None
        else:
            try:
                results = await self._client.async_get_bluetooth_scan_results(device)
            except BluetoothScanUnsupported:
                self._mark_unsupported(device_id, speaker)
                return
            except BluetoothScanError as err:
                _LOGGER.debug("Failed to read Bluetooth scan: %s", err)
                speaker.run_start = None
            else:
                speaker.answered = True
                self._read_scan(speaker, start, results)
        start = self._clock()
        try:
            await self._client.async_start_bluetooth_scan(device)
        except BluetoothScanUnsupported:
            self._mark_unsupported(device_id, speaker)
        except BluetoothScanError as err:
            # It may have cleared the results or not, so they're never read
            _LOGGER.debug("Failed to start Bluetooth scan: %s", err)
        else:
            speaker.pending_start = start

    def _read_scan(
        self, speaker: SpeakerScan, start: float, results: list[BluetoothJsonDict]
    ) -> None:
        """Record the sightings of a scan that started at start, if it's recent."""
        read = self._clock()
        if read - start > BLUETOOTH_MAX_RESULT_AGE:
            _LOGGER.debug(
                "Discarded Bluetooth scan of %s read %.0f seconds after it started",
                speaker.name,
                read - start,
            )
            speaker.run_start = None
            return
        # Only counts: the results include the neighbours' devices
        _LOGGER.debug("%s heard %d Bluetooth devices", speaker.name, len(results))
        for result in results:
            if result["rssi"] < BLUETOOTH_MIN_RSSI:
                continue
            address = normalize_mac(result["mac_address"])
            if address is None:
                continue
            for device in self.tracked:
                if device.matches(address) and (
                    device.last_sighted is None or device.last_sighted < start
                ):
                    # The scan's start, as the device may have been heard then
                    device.last_sighted = start
        if (
            speaker.run_start is None
            or speaker.covered_until is None
            or start > speaker.covered_until + BLUETOOTH_MAX_SCAN_GAP
        ):
            speaker.run_start = start
        speaker.covered_until = min(read, start + BLUETOOTH_SCAN_INTERVAL)

    def _mark_unsupported(self, device_id: str, speaker: SpeakerScan) -> None:
        """Stop scanning with a speaker that has no Bluetooth scan endpoint."""
        _LOGGER.debug(
            "%s doesn't support Bluetooth scans, not using it until reload",
            speaker.name,
        )
        self._unsupported.add(device_id)
        self._speakers.pop(device_id, None)

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
                and now - speaker.uncovered_since >= BLUETOOTH_BLOCKING_WARNING
            ):
                speaker.warned = True
                _LOGGER.warning(
                    "%s hasn't answered Bluetooth scans for %d minutes, so Bluetooth "
                    "trackers can't show away. If it's out of service, add it to "
                    "'Speakers not used for Bluetooth tracking' in the integration's "
                    "options",
                    speaker.name,
                    BLUETOOTH_BLOCKING_WARNING // 60,
                )

    @staticmethod
    def _state(device: TrackedDevice, now: float, covered: bool) -> TrackerState:
        """Return the state of a tracked device after an update."""
        if (
            device.last_sighted is not None
            and device.last_sighted > now - BLUETOOTH_PRESENCE_WINDOW
        ):
            state = TrackerState.HOME
        elif covered:
            state = TrackerState.NOT_HOME
        elif device.state_known:
            return TrackerState.UNAVAILABLE
        else:
            return TrackerState.UNKNOWN
        device.state_known = True
        return state
