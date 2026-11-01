"""Bluetooth presence tracking with the Bluetooth scans of Google Home devices.

Each update reads the results of the scan that every speaker started in the
previous update, then starts the next scan. A tracked device is home while a
speaker heard it recently. It's away only when every speaker that Google lists
and that has returned scan results since setup has scanned without a break for
the whole presence window and none heard it: a speaker that stops answering
can't confirm that a device is gone. Meanwhile the tracker keeps its last state for a few minutes,
so a missed scan doesn't make it flap. A device that never returned results,
such as a TV that refuses the connection instead of answering 404, can't keep
trackers from showing away.
"""

import asyncio
import base64
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
import logging
import re
from time import monotonic
from typing import Literal, cast

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp.client_exceptions import ContentTypeError
from bluetooth_data_tools import get_cipher_for_irk, resolve_private_address

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MAC

from .const import (
    API_ENDPOINT_BLUETOOTH_RESULTS,
    API_ENDPOINT_BLUETOOTH_SCAN,
    BLUETOOTH_MAX_RESULT_AGE,
    BLUETOOTH_MAX_SCAN_GAP,
    BLUETOOTH_MIN_RSSI,
    BLUETOOTH_PRESENCE_WINDOW,
    BLUETOOTH_SCAN_INTERVAL,
    BLUETOOTH_UNCERTAIN_LIMIT,
    CONF_IRK,
    HEADER_CAST_LOCAL_AUTH,
    HEADER_CONTENT_TYPE,
    PORT,
    TIMEOUT,
)
from .coordinator import GoogleAccountCoordinator
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
    and raises instead of logging, as Bluetooth updates run every 30 seconds.
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
            timeout=ClientTimeout(total=TIMEOUT),
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
        # The latest home or away state, and when the speakers last confirmed it
        self.state = TrackerState.UNKNOWN
        self.confirmed_at: float | None = None

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
        session: ClientSession,
        account: GoogleAccountCoordinator,
        subentries: Iterable[ConfigSubentry],
        excluded: Iterable[str],
    ) -> None:
        """Create a scanner for the tracked devices, using the devices Google lists."""
        self._session = session
        self._account = account
        self.tracked = [TrackedDevice(subentry) for subentry in subentries]
        self._excluded = set(excluded)
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
        now = monotonic()
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
        devices = dict(self._account.data or {})
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
                results = await async_get_bluetooth_scan_results(self._session, device)
            except BluetoothScanUnsupported:
                self._mark_unsupported(device_id, speaker)
                return
            except BluetoothScanError as err:
                _LOGGER.debug("Failed to read Bluetooth scan: %s", err)
                speaker.run_start = None
            else:
                speaker.answered = True
                self._read_scan(speaker, start, results)
        start = monotonic()
        try:
            await async_start_bluetooth_scan(self._session, device)
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
        read = monotonic()
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
                and now - speaker.uncovered_since >= BLUETOOTH_UNCERTAIN_LIMIT
            ):
                speaker.warned = True
                _LOGGER.warning(
                    "%s hasn't answered Bluetooth scans for %d minutes, so Bluetooth "
                    "trackers can't show away. If it's out of service, add it to "
                    "'Speakers not used for Bluetooth tracking' in the integration's "
                    "options",
                    speaker.name,
                    BLUETOOTH_UNCERTAIN_LIMIT // 60,
                )

    @staticmethod
    def _state(device: TrackedDevice, now: float, covered: bool) -> TrackerState:
        """Return the state of a tracked device after an update.

        When the speakers can't tell, the last state stays for a few minutes:
        a missed scan, or a speaker coming online, doesn't make it flap.
        """
        if (
            device.last_sighted is not None
            and device.last_sighted > now - BLUETOOTH_PRESENCE_WINDOW
        ):
            device.state, device.confirmed_at = TrackerState.HOME, now
        elif covered:
            device.state, device.confirmed_at = TrackerState.NOT_HOME, now
        elif device.confirmed_at is None:
            return TrackerState.UNKNOWN
        elif now - device.confirmed_at >= BLUETOOTH_UNCERTAIN_LIMIT:
            return TrackerState.UNAVAILABLE
        return device.state
