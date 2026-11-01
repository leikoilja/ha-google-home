"""Tests for Bluetooth presence tracking: the scanner, the tracker and the requests.

The scanner's tests fake the speakers' Bluetooth requests and the clock. The tests
that run inside Home Assistant are in test_bluetooth_setup.py.
"""

import asyncio
import base64
import logging
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aiohttp import ClientError
from bluetooth_data_tools import get_cipher_for_irk
import pytest

from custom_components.google_home import (
    async_create_bluetooth_coordinator,
    async_update_entry,
    bluetooth_config,
)
from custom_components.google_home.bluetooth import (
    BluetoothScanError,
    BluetoothScanner,
    BluetoothScanUnsupported,
    TrackedDevice,
    TrackerState,
    TrackerUpdate,
    async_get_bluetooth_scan_results,
    async_start_bluetooth_scan,
    normalize_mac,
    parse_irk,
)
from custom_components.google_home.device_tracker import GoogleHomeBluetoothTracker
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.config_entries import ConfigSubentry

BLUETOOTH = "custom_components.google_home.bluetooth"
IRK = bytes(range(16))
PHONE = "phone"


def rpa(irk: bytes, prand: bytes = b"\x52\x34\x56") -> str:
    """Return a resolvable private address that the IRK resolves."""
    encryptor = get_cipher_for_irk(irk).encryptor()
    digest = (encryptor.update(bytes(13) + prand) + encryptor.finalize())[13:]
    return ":".join(f"{byte:02X}" for byte in prand + digest)


def subentry(
    data: dict[str, str], subentry_id: str = PHONE, title: str = "Phone"
) -> ConfigSubentry:
    """Return a tracked device's subentry as the subentry flow saves it."""
    return ConfigSubentry(
        data=MappingProxyType(data),
        subentry_id=subentry_id,
        subentry_type="bluetooth_device",
        title=title,
        unique_id=None,
    )


def heard(address: str, rssi: int = -50) -> BluetoothJsonDict:
    """Return a scan result."""
    return {"mac_address": address, "rssi": rssi}


class Speakers:
    """Fake speakers that answer the scanner's Bluetooth requests."""

    def __init__(self, *names: str) -> None:
        """Create speakers with addresses and tokens."""
        self.devices = [
            GoogleHomeDevice(name.lower(), name, "token", ip_address=f"10.0.0.{i}")
            for i, name in enumerate(names, 1)
        ]
        # What each speaker's scan results hold, by device ID
        self.results: dict[str, list[BluetoothJsonDict]] = {}
        self.failing: set[str] = set()
        self.failing_start: set[str] = set()
        self.unsupported: set[str] = set()
        self.reads: list[str] = []
        self.starts: list[str] = []
        # Every request, including those that fail
        self.asked: list[str] = []

    async def async_get_bluetooth_scan_results(
        self, _session: object, device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        """Return what the speaker heard."""
        self._raise_if_failing(device)
        self.reads.append(device.device_id)
        return self.results.get(device.device_id, [])

    async def async_start_bluetooth_scan(
        self, _session: object, device: GoogleHomeDevice
    ) -> None:
        """Start a scan."""
        self._raise_if_failing(device)
        if device.device_id in self.failing_start:
            raise BluetoothScanError("timeout")
        self.starts.append(device.device_id)

    def _raise_if_failing(self, device: GoogleHomeDevice) -> None:
        self.asked.append(device.device_id)
        if device.device_id in self.unsupported:
            raise BluetoothScanUnsupported("404")
        if device.device_id in self.failing:
            raise BluetoothScanError("offline")


def make_scanner(
    speakers: Speakers,
    tracked: list[ConfigSubentry] | None = None,
    excluded: list[str] | None = None,
) -> BluetoothScanner:
    """Return a scanner using the fake speakers, as the account lists them."""
    return BluetoothScanner(
        Mock(),
        Mock(data={device.device_id: device for device in speakers.devices}),
        tracked or [subentry({"irk": IRK.hex()})],
        excluded or [],
    )


def run(scanner: BluetoothScanner, speakers: Speakers, now: float) -> TrackerUpdate:
    """Run an update at a time and return the phone's update."""
    with (
        patch(f"{BLUETOOTH}.monotonic", return_value=now),
        patch(
            f"{BLUETOOTH}.async_get_bluetooth_scan_results",
            speakers.async_get_bluetooth_scan_results,
        ),
        patch(
            f"{BLUETOOTH}.async_start_bluetooth_scan",
            speakers.async_start_bluetooth_scan,
        ),
    ):
        return asyncio.run(scanner.async_update())[PHONE]


def update(scanner: BluetoothScanner, speakers: Speakers, now: float) -> TrackerState:
    """Run an update at a time and return the phone's state."""
    return run(scanner, speakers, now).state


def states(
    scanner: BluetoothScanner, speakers: Speakers, times: range
) -> list[TrackerState]:
    """Run updates at these times and return the phone's states."""
    return [update(scanner, speakers, now) for now in times]


HOME = TrackerState.HOME
NOT_HOME = TrackerState.NOT_HOME
UNKNOWN = TrackerState.UNKNOWN
UNAVAILABLE = TrackerState.UNAVAILABLE


@pytest.mark.parametrize(
    "value",
    [
        IRK.hex(),
        IRK.hex().upper(),
        ":".join(f"{byte:02x}" for byte in IRK),
        f"irk:{IRK.hex()}",
        f"0x{IRK.hex()}",
        # As macOS Keychain shows it: base64, in reverse byte order
        base64.b64encode(IRK[::-1]).decode(),
    ],
)
def test_parse_irk(value: str) -> None:
    """Accept the formats Home Assistant's Private BLE Device accepts."""
    assert parse_irk(f" {value} ") == IRK


@pytest.mark.parametrize(
    "value", ["", "not an irk", IRK.hex()[:-2], IRK.hex() + "00", "AAAA=", "%%%%="]
)
def test_parse_irk_rejects(value: str) -> None:
    """Reject anything that isn't 16 bytes."""
    assert parse_irk(value) is None


@pytest.mark.parametrize(
    "value",
    ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabbccddeeff", "aabb.ccdd.eeff"],
)
def test_normalize_mac(value: str) -> None:
    """Accept common MAC address formats."""
    assert normalize_mac(value) == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize("value", ["", "aa:bb:cc:dd:ee", "gg:bb:cc:dd:ee:ff"])
def test_normalize_mac_rejects(value: str) -> None:
    """Reject anything that isn't 12 hex digits."""
    assert normalize_mac(value) is None


def test_irk_matches_only_its_addresses() -> None:
    """Match resolvable private addresses of the IRK only."""
    device = TrackedDevice(subentry({"irk": IRK.hex()}))

    assert device.matches(rpa(IRK))
    assert not device.matches(rpa(bytes(16)))
    # A public address isn't resolvable, whatever its bytes
    assert not device.matches("00" + rpa(IRK)[2:])


def test_mac_matches_address() -> None:
    """Match a tracked MAC address however the speaker writes it."""
    speakers = Speakers("Kitchen")
    speakers.results["kitchen"] = [heard("aa:bb:cc:dd:ee:ff")]
    scanner = make_scanner(speakers, [subentry({"mac": "AA:BB:CC:DD:EE:FF"})])

    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, HOME]


def test_phone_in_range_after_setup() -> None:
    """Show a phone in range as home once the first scan is read."""
    speakers = Speakers("Kitchen")
    speakers.results["kitchen"] = [heard(rpa(IRK))]
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, HOME]


def test_phone_away_after_setup() -> None:
    """Show a phone as away once the speaker scanned for the whole window."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 120, 30)) == [
        UNKNOWN,
        UNKNOWN,
        UNKNOWN,
        NOT_HOME,
    ]


def test_phone_leaves_and_returns() -> None:
    """Show away exactly 90 seconds after the start of the last scan that heard it."""
    speakers = Speakers("Kitchen")
    speakers.results["kitchen"] = [heard(rpa(IRK))]
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 90, 30)) == [UNKNOWN, HOME, HOME]

    # The scan that started at 30 was the last to hear it
    speakers.results["kitchen"] = []
    assert states(scanner, speakers, range(90, 150, 30)) == [HOME, NOT_HOME]

    speakers.results["kitchen"] = [heard(rpa(IRK, b"\x61\x00\x01"))]
    assert update(scanner, speakers, 150) == HOME


def test_several_addresses_in_one_scan() -> None:
    """Match the phone's old and new address heard in the same scan."""
    speakers = Speakers("Kitchen")
    speakers.results["kitchen"] = [
        heard(rpa(IRK), -70),
        heard(rpa(IRK, b"\x43\x74\x2b"), -40),
    ]
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, HOME]


@pytest.mark.parametrize(("rssi", "state"), [(-80, HOME), (-81, NOT_HOME)])
def test_ignore_weak_sightings(rssi: int, state: TrackerState) -> None:
    """Ignore sightings weaker than -80 dBm, like a phone heard from outside."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    states(scanner, speakers, range(0, 120, 30))

    speakers.results["kitchen"] = [heard(rpa(IRK), rssi)]
    assert update(scanner, speakers, 120) == state


def test_failed_scan_start_skips_next_read() -> None:
    """Never read results after a scan failed to start, as they may be old."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME

    # Reading works but starting the next scan times out, maybe after clearing
    speakers.failing_start.add("kitchen")
    assert update(scanner, speakers, 120) == NOT_HOME
    speakers.failing_start.clear()
    # The old results hold the phone, but aren't read: it stays away
    speakers.results["kitchen"] = [heard(rpa(IRK))]
    speakers.reads.clear()
    assert update(scanner, speakers, 150) == NOT_HOME
    assert not speakers.reads


def test_recover_after_failed_scan_start() -> None:
    """Confirm away again 120 seconds after the last scan that failed to start."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    states(scanner, speakers, range(0, 150, 30))

    # Starting scans fails from 150 to 450. The update at 150 still reads the
    # scan started at 120, so away is last confirmed then.
    speakers.failing_start.add("kitchen")
    assert states(scanner, speakers, range(150, 450, 30)) == [NOT_HOME] * 10
    assert update(scanner, speakers, 450) == UNAVAILABLE
    speakers.failing_start.clear()

    # The next scan starts at 480, so away is confirmed again at 480 + 90
    assert states(scanner, speakers, range(480, 600, 30)) == [
        UNAVAILABLE,
        UNAVAILABLE,
        UNAVAILABLE,
        NOT_HOME,
    ]


def test_discard_delayed_results() -> None:
    """Discard results read more than 45 seconds after their scan started."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    states(scanner, speakers, range(0, 120, 30))

    speakers.results["kitchen"] = [heard(rpa(IRK))]
    # The update after 90 is delayed until 300: the phone it heard isn't used
    assert update(scanner, speakers, 300) == NOT_HOME
    # The scan started at 300 is read on time: heard, and the run starts again
    assert update(scanner, speakers, 330) == HOME
    speakers.results["kitchen"] = []
    assert states(scanner, speakers, range(360, 420, 30)) == [HOME, NOT_HOME]


def test_new_token_skips_next_read() -> None:
    """Don't read a scan started with a token the speaker no longer has."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    update(scanner, speakers, 0)

    speakers.devices[0].auth_token = "new-token"
    speakers.reads.clear()
    update(scanner, speakers, 30)

    assert not speakers.reads
    assert speakers.starts == ["kitchen", "kitchen"]


def test_speaker_that_stops_answering_never_shows_away() -> None:
    """Keep home, then show unavailable, when the speaker that heard the phone stops answering."""
    speakers = Speakers("Bedroom", "Kitchen")
    speakers.results["bedroom"] = [heard(rpa(IRK))]
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 90, 30)) == [UNKNOWN, HOME, HOME]

    # The last bedroom scan to hear it started at 30, so home is last confirmed
    # at 90; the kitchen hears nothing
    speakers.failing.add("bedroom")
    assert (
        states(scanner, speakers, range(90, 600, 30)) == [HOME] * 10 + [UNAVAILABLE] * 7
    )


def test_new_speaker_coming_online_keeps_away() -> None:
    """Stay away while a speaker found later scans for the whole window."""
    speakers = Speakers("Kitchen")
    bedroom = GoogleHomeDevice("bedroom", "Bedroom", "token")
    speakers.devices.append(bedroom)
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME

    bedroom.ip_address = "10.0.0.9"
    assert states(scanner, speakers, range(120, 240, 30)) == [NOT_HOME] * 4

    # Until it has, it can't confirm away: a phone it alone hears shows home
    speakers.results["bedroom"] = [heard(rpa(IRK))]
    assert update(scanner, speakers, 240) == HOME


def test_missed_scan_keeps_away() -> None:
    """Stay away, never unavailable, when a speaker misses a scan."""
    speakers = Speakers("Kitchen", "Hallway")
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME

    speakers.failing.add("hallway")
    assert update(scanner, speakers, 120) == NOT_HOME
    speakers.failing.clear()

    assert states(scanner, speakers, range(150, 360, 30)) == [NOT_HOME] * 7


def test_no_speakers_never_shows_away() -> None:
    """Keep unknown when no speaker has an address and token to scan with."""
    speakers = Speakers("Kitchen")
    speakers.devices[0].ip_address = None
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 300, 30)) == [UNKNOWN] * 10
    assert not speakers.starts


def test_unsupported_speakers_never_show_away() -> None:
    """Keep unknown when every speaker returns 404, and stop asking them."""
    speakers = Speakers("Kitchen")
    speakers.unsupported.add("kitchen")
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 300, 30)) == [UNKNOWN] * 10
    # Only the first scan was asked for
    assert speakers.asked == ["kitchen"]


def test_unsupported_speaker_left_out() -> None:
    """Confirm away with the speakers that support scans."""
    speakers = Speakers("Kitchen", "Hub")
    speakers.unsupported.add("hub")
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME


@pytest.mark.parametrize("fails", ["timeout", "unsupported"])
def test_device_that_never_answers_never_blocks_away(fails: str) -> None:
    """Confirm away without a device that never returned results, however it fails."""
    speakers = Speakers("Kitchen", "TV")
    if fails == "timeout":
        speakers.failing.add("tv")
    else:
        speakers.unsupported.add("tv")
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME


def test_excluded_speaker_not_used() -> None:
    """Never ask an excluded speaker, and confirm away without it."""
    speakers = Speakers("Kitchen", "Garage")
    speakers.failing.add("garage")
    scanner = make_scanner(speakers, excluded=["garage"])

    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME
    assert "garage" not in speakers.starts


def test_warn_about_speaker_that_blocks_away(caplog: pytest.LogCaptureFixture) -> None:
    """Warn once when a speaker has kept trackers from showing away for 5 minutes."""
    speakers = Speakers("Kitchen", "Garage")
    scanner = make_scanner(speakers)
    states(scanner, speakers, range(0, 60, 30))
    speakers.failing.add("garage")

    def warnings() -> list[str]:
        return [
            record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        ]

    states(scanner, speakers, range(60, 330, 30))
    assert not warnings()
    states(scanner, speakers, range(330, 600, 30))

    (warning,) = warnings()
    assert warning.startswith("Garage hasn't answered Bluetooth scans for 5 minutes")


def test_speakers_show_median_rssi_over_window() -> None:
    """Show each speaker's median RSSI, strongest first, once the window completes.

    A speaker needs two readings of -80 dBm or stronger in the window.
    """
    speakers = Speakers("Kitchen", "Bedroom", "Garage", "Office")
    scanner = make_scanner(speakers)
    phone = rpa(IRK)
    others = {
        60: {"bedroom": -40},
        90: {"garage": -80},
        120: {"office": -81},
        240: {"bedroom": -46},
        270: {"garage": -78},
        300: {"office": -60},
    }

    assert run(scanner, speakers, 0) == TrackerUpdate(UNKNOWN, {})
    # Home from 30, so the window runs to 330
    # A strong reflection first, and a reading too weak to count last
    kitchen = [-30, -52, -54, -56, -58, -60, -62, -64, -66, -68, -90]
    shown = []
    for now, value in zip(range(30, 331, 30), kitchen, strict=True):
        rssi = {"kitchen": value, **others.get(now, {})}
        speakers.results = {
            speaker: [heard(phone, strength)] for speaker, strength in rssi.items()
        }
        shown.append(run(scanner, speakers, now))

    assert shown[:-1] == [TrackerUpdate(HOME, {})] * 10
    # Kitchen: the middle two of its ten readings that count, -58 and -60, which the
    # reflection doesn't move. Office has only one reading strong enough.
    assert list(shown[-1].speakers.items()) == [
        ("Bedroom", -43),
        ("Kitchen", -59),
        ("Garage", -79),
    ]
    # The next window has only just started
    speakers.results = {"kitchen": [heard(phone, -70)]}
    assert run(scanner, speakers, 360).speakers == shown[-1].speakers


def test_speakers_empty_after_window_without_two_readings() -> None:
    """Show no speakers after a window in which none heard the phone twice, even if it stays home."""
    speakers = Speakers("Kitchen", "Bedroom")
    scanner = make_scanner(speakers)
    speakers.results = {"kitchen": [heard(rpa(IRK))], "bedroom": [heard(rpa(IRK))]}
    assert states(scanner, speakers, range(0, 330, 30))[-1] == HOME
    assert run(scanner, speakers, 330).speakers == {"Bedroom": -50, "Kitchen": -50}

    # Kitchen stops answering, so the phone stays home, and Bedroom hears it once more
    speakers.failing.add("kitchen")
    run(scanner, speakers, 360)
    speakers.results = {}
    shown = [run(scanner, speakers, now) for now in range(390, 631, 30)]

    assert shown[-2] == TrackerUpdate(HOME, {"Bedroom": -50, "Kitchen": -50})
    assert shown[-1] == TrackerUpdate(HOME, {})


def test_speakers_restart_when_state_changes() -> None:
    """Show no speakers as soon as the phone leaves, and until a full window after it returns.

    Readings from before it left never count after it returns.
    """
    speakers = Speakers("Kitchen", "Bedroom")
    scanner = make_scanner(speakers)
    phone = rpa(IRK)
    speakers.results = {"kitchen": [heard(phone, -60)]}
    assert states(scanner, speakers, range(0, 330, 30))[-1] == HOME
    assert run(scanner, speakers, 330).speakers == {"Kitchen": -60}

    # Bedroom hears it twice before it leaves
    speakers.results["bedroom"] = [heard(phone, -40)]
    states(scanner, speakers, range(360, 420, 30))
    speakers.results = {}
    # The scan that started at 360 was the last to hear it
    assert run(scanner, speakers, 420) == TrackerUpdate(HOME, {"Kitchen": -60})
    assert run(scanner, speakers, 450) == TrackerUpdate(NOT_HOME, {})

    # Home again at 480, so the window runs to 780
    speakers.results = {"kitchen": [heard(phone, -70)]}
    shown = [run(scanner, speakers, now) for now in range(480, 781, 30)]

    assert shown[:-1] == [TrackerUpdate(HOME, {})] * 10
    assert shown[-1] == TrackerUpdate(HOME, {"Kitchen": -70})


def test_speakers_count_one_reading_per_scan() -> None:
    """Count the phone's old and new address heard in one scan as one reading, at the stronger RSSI."""
    speakers = Speakers("Kitchen", "Bedroom")
    scanner = make_scanner(speakers)
    both = [heard(rpa(IRK, b"\x43\x74\x2b"), -50), heard(rpa(IRK), -70)]
    speakers.results = {"kitchen": both, "bedroom": both}
    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, HOME]

    # Bedroom heard it in only one scan of the window that started at 30
    speakers.results = {"kitchen": both}
    states(scanner, speakers, range(60, 330, 30))

    assert run(scanner, speakers, 330).speakers == {"Kitchen": -50}


def test_speakers_count_only_fresh_scans() -> None:
    """Leave out readings from a scan read too late to count for presence."""
    speakers = Speakers("Kitchen", "Bedroom")
    scanner = make_scanner(speakers)
    speakers.results = {"kitchen": [heard(rpa(IRK), -60)]}
    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, HOME]

    # Bedroom hears it in two scans, but the update after 120 is delayed until
    # 180, so the second scan's results are discarded
    states(scanner, speakers, range(60, 120, 30))
    speakers.results["bedroom"] = [heard(rpa(IRK), -40)]
    run(scanner, speakers, 120)
    assert run(scanner, speakers, 180).state == HOME
    del speakers.results["bedroom"]
    states(scanner, speakers, range(210, 330, 30))

    assert run(scanner, speakers, 330) == TrackerUpdate(HOME, {"Kitchen": -60})


def test_speakers_with_same_name_count_separately() -> None:
    """Count each speaker's own readings, even when two speakers share a name.

    Speakers that share a name share an entry, with the stronger median.
    """
    speakers = Speakers("Kitchen", "Bedroom", "Office")
    speakers.devices[1].name = "Kitchen"
    scanner = make_scanner(speakers)
    phone = rpa(IRK)
    speakers.results = {"office": [heard(phone, -60)]}
    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, HOME]

    # In the window that started at 30, each speaker named Kitchen hears the
    # phone once, while Office keeps it home
    speakers.results["kitchen"] = [heard(phone, -40)]
    run(scanner, speakers, 60)
    speakers.results = {"office": [heard(phone, -60)], "bedroom": [heard(phone, -44)]}
    run(scanner, speakers, 90)
    speakers.results = {"office": [heard(phone, -60)]}
    states(scanner, speakers, range(120, 330, 30))
    assert run(scanner, speakers, 330).speakers == {"Office": -60}

    # In the next window, both hear it in every scan
    speakers.results.update(kitchen=[heard(phone, -50)], bedroom=[heard(phone, -70)])
    states(scanner, speakers, range(360, 630, 30))
    assert run(scanner, speakers, 630).speakers == {"Kitchen": -50, "Office": -60}


def test_speakers_named_as_google_lists_them() -> None:
    """Show a speaker renamed partway through a window by its new name only."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    speakers.results = {"kitchen": [heard(rpa(IRK))]}
    assert states(scanner, speakers, range(0, 180, 30))[-1] == HOME

    speakers.devices[0].name = "Lounge"
    states(scanner, speakers, range(180, 330, 30))

    assert run(scanner, speakers, 330).speakers == {"Lounge": -50}


def tracker(data: dict[str, TrackerUpdate] | None) -> GoogleHomeBluetoothTracker:
    """Return the phone's tracker, with the coordinator's latest states."""
    coordinator = Mock(data=data, last_update_success=True)
    return GoogleHomeBluetoothTracker(coordinator, subentry({"irk": IRK.hex()}))


@pytest.mark.parametrize(
    ("state", "is_connected", "available"),
    [
        (HOME, True, True),
        (NOT_HOME, False, True),
        (UNKNOWN, None, True),
        (UNAVAILABLE, None, False),
    ],
)
def test_tracker_state(
    state: TrackerState, is_connected: bool | None, available: bool
) -> None:
    """Show home, away, unknown or unavailable."""
    entity = tracker({PHONE: TrackerUpdate(state, {})})

    assert entity.is_connected is is_connected
    assert entity.available is available


def test_tracker_unknown_before_first_update() -> None:
    """Start unknown, before the first update has states."""
    assert tracker(None).is_connected is None


def test_tracker_unavailable_when_update_fails() -> None:
    """Show unavailable after an update that failed unexpectedly, whatever the last state."""
    entity = tracker({PHONE: TrackerUpdate(HOME, {})})
    entity.coordinator.last_update_success = False

    assert not entity.available


def make_entry(
    options: dict[str, object], subentries: list[ConfigSubentry] | None = None
) -> Mock:
    """Return a config entry with these options and tracked devices."""
    entry = Mock(entry_id="entry", options=options)
    entry.get_subentries_of_type.return_value = subentries or []
    return entry


@pytest.mark.parametrize(
    ("options", "subentries"),
    [
        ({}, [subentry({"irk": IRK.hex()})]),
        ({"bluetooth_tracking": False}, [subentry({"irk": IRK.hex()})]),
        ({"bluetooth_tracking": True}, []),
    ],
)
def test_no_scanning_when_off_or_nothing_tracked(
    options: dict[str, object], subentries: list[ConfigSubentry]
) -> None:
    """Send no Bluetooth requests while tracking is off or tracks nothing."""
    entry = make_entry(options, subentries)

    assert async_create_bluetooth_coordinator(Mock(), entry, Mock()) is None


def test_scanner_never_raises() -> None:
    """Never fail an update, so Bluetooth can't fail or delay setup."""
    speakers = Speakers("Kitchen")
    speakers.failing.add("kitchen")
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, UNKNOWN]


def run_update_listener(entry: Mock, setup_entry: Mock) -> Mock:
    """Run the update listener after the entry's options changed and return Home Assistant."""
    hass = Mock()
    entry.runtime_data = Mock(
        client=Mock(known_hosts=[], excluded_homes=set()),
        devices={},
        bluetooth_config=bluetooth_config(setup_entry),
    )
    asyncio.run(async_update_entry(hass, entry))
    return hass


@pytest.mark.parametrize(
    "options",
    [
        {"bluetooth_tracking": True},
        {"bluetooth_tracking": False, "bluetooth_excluded_speakers": ["garage"]},
    ],
)
def test_reload_when_bluetooth_options_change(options: dict[str, object]) -> None:
    """Reload when tracking is turned on or off, or speakers are excluded."""
    hass = run_update_listener(make_entry(options), make_entry({}))

    hass.config_entries.async_schedule_reload.assert_called_once_with("entry")


def test_no_reload_when_only_interval_changes() -> None:
    """Change the update interval in place, as before."""
    hass = run_update_listener(
        make_entry({"update_interval": 60}), make_entry({"update_interval": 180})
    )

    hass.config_entries.async_schedule_reload.assert_not_called()


def mock_session(status: int = 200, body: object = None) -> Mock:
    """Return a session whose device answers with this status and JSON body."""
    response = MagicMock()
    response.__aenter__.return_value = Mock(
        status=status, json=AsyncMock(return_value=body)
    )
    return Mock(request=Mock(return_value=response))


KITCHEN = GoogleHomeDevice("kitchen", "Kitchen", "token", ip_address="10.0.0.1")


def test_start_scan_request() -> None:
    """Start a 30-second scan that clears the previous results."""
    session = mock_session()

    asyncio.run(async_start_bluetooth_scan(session, KITCHEN))

    method, url = session.request.call_args.args
    assert (method, url) == ("POST", "https://10.0.0.1:8443/setup/bluetooth/scan")
    assert session.request.call_args.kwargs["json"] == {
        "enable": True,
        "clear_results": True,
        "timeout": 30,
    }
    assert (
        session.request.call_args.kwargs["headers"]["cast-local-authorization-token"]
        == "token"
    )


def test_scan_results_skip_malformed_entries() -> None:
    """Return the address and signal strength of each well-formed result."""
    session = mock_session(
        body=[
            {"mac_address": "AA:BB:CC:DD:EE:FF", "rssi": -50, "name": ""},
            {"mac_address": "AA:BB:CC:DD:EE:00"},
            "garbage",
        ]
    )

    results = asyncio.run(async_get_bluetooth_scan_results(session, KITCHEN))

    assert results == [{"mac_address": "AA:BB:CC:DD:EE:FF", "rssi": -50}]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (404, None, BluetoothScanUnsupported),
        (401, None, BluetoothScanError),
        (500, None, BluetoothScanError),
        (200, {"error": "no list"}, BluetoothScanError),
    ],
)
def test_scan_results_errors(
    status: int, body: object, error: type[BluetoothScanError]
) -> None:
    """Raise for 404 as unsupported, and for other failures as errors."""
    session = mock_session(status, body)

    with pytest.raises(error):
        asyncio.run(async_get_bluetooth_scan_results(session, KITCHEN))


def test_request_failure_leaves_device_available() -> None:
    """Raise on a connection error without marking the device unavailable."""
    session = mock_session()
    session.request.side_effect = ClientError("offline")
    device = GoogleHomeDevice("kitchen", "Kitchen", "token", ip_address="10.0.0.1")

    with pytest.raises(BluetoothScanError):
        asyncio.run(async_start_bluetooth_scan(session, device))
    assert device.available
