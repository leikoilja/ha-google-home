"""Tests for Bluetooth presence tracking.

The scanner's tests fake the speakers' Bluetooth requests and the clock. The rest
run the integration inside Home Assistant with the fixtures in conftest.py, and
fake only the Bluetooth requests, which the speakers' replies table doesn't have.
"""

import asyncio
import base64
from collections.abc import Iterator
import json
import logging
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aiohttp import ClientError
from bluetooth_data_tools import get_cipher_for_irk
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator, WebSocketGenerator

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
    async_get_bluetooth_scan_results,
    async_start_bluetooth_scan,
    normalize_mac,
    parse_irk,
)
from custom_components.google_home.device_tracker import GoogleHomeBluetoothTracker
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import (
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import SPEAKER_ID, SPEAKER_NAME
from .test_coordinators import runtime
from .test_removed_devices import fetch_list
from .test_setup import set_up
from .test_unsupported_devices import SPEAKER

# pylint: enable=wrong-import-order

BLUETOOTH = "custom_components.google_home.bluetooth"
IRK = bytes(range(16))
PHONE = "phone"
TRACKER = "device_tracker.phone"


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


def update(scanner: BluetoothScanner, speakers: Speakers, now: float) -> TrackerState:
    """Run an update at a time and return the phone's state."""
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


def tracker(data: dict[str, TrackerState] | None) -> GoogleHomeBluetoothTracker:
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
    entity = tracker({PHONE: state})

    assert entity.is_connected is is_connected
    assert entity.available is available


def test_tracker_unknown_before_first_update() -> None:
    """Start unknown, before the first update has states."""
    assert tracker(None).is_connected is None


def test_tracker_writes_only_changes() -> None:
    """Write the state only when it changes, so history gets no row every update."""
    data = {PHONE: HOME}
    entity = tracker(data)

    with patch.object(entity, "async_write_ha_state") as write:
        entity._handle_coordinator_update()  # noqa: SLF001  # pylint: disable=protected-access
        write.assert_not_called()

        data[PHONE] = NOT_HOME
        entity._handle_coordinator_update()  # noqa: SLF001  # pylint: disable=protected-access
        write.assert_called_once()


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


class Scans:
    """What each speaker's Bluetooth scans hear, by address, and the clock they read."""

    def __init__(self) -> None:
        """Start with scans that hear nothing, at time 0."""
        self.heard: dict[str, list[BluetoothJsonDict]] = {}
        self.now = 0.0
        # The speakers asked to start a scan, in order
        self.started: list[str] = []

    async def results(
        self, _session: object, device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        """Return what the speaker heard."""
        return self.heard.get(str(device.ip_address), [])

    async def start(self, _session: object, device: GoogleHomeDevice) -> None:
        """Start a scan."""
        self.started.append(device.name)


@pytest.fixture(name="scans")
def fixture_scans() -> Iterator[Scans]:
    """Fake the speakers' Bluetooth scans and the scanner's clock."""
    scans = Scans()
    with (
        patch(f"{BLUETOOTH}.async_get_bluetooth_scan_results", scans.results),
        patch(f"{BLUETOOTH}.async_start_bluetooth_scan", scans.start),
        patch(f"{BLUETOOTH}.monotonic", lambda: scans.now),
    ):
        yield scans


async def scan(
    hass: HomeAssistant, entry: MockConfigEntry, scans: Scans, now: float
) -> str:
    """Run the Bluetooth update at a time and return the phone's tracker state."""
    scans.now = now
    coordinator = runtime(entry).bluetooth
    assert coordinator is not None
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(TRACKER)
    assert state is not None
    return state.state


async def track_phone(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Turn Bluetooth tracking on, track the phone by its IRK, and set up the entry."""
    hass.config_entries.async_update_entry(entry, options={"bluetooth_tracking": True})
    hass.config_entries.async_add_subentry(entry, subentry({"irk": IRK.hex()}))
    await set_up(hass, entry)


async def add_device(
    hass: HomeAssistant, entry: MockConfigEntry, user_input: dict[str, str]
) -> dict[str, object]:
    """Fill in the form that adds a tracked device, and return the result."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "bluetooth_device"), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    return dict(
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], user_input
        )
    )


@pytest.mark.usefixtures("google", "replies")
async def test_track_phone(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Add a phone, show it home while the speaker hears it and away once it's gone, then remove it."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    await set_up(hass, config_entry)
    # Nothing is tracked yet
    assert runtime(config_entry).bluetooth is None

    result = await add_device(hass, config_entry, {"name": "Phone", "irk": IRK.hex()})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Adding it reloads the entry, which starts the first scans in the background
    await hass.async_block_till_done(wait_background_tasks=True)

    assert config_entry.state is ConfigEntryState.LOADED
    assert scans.started == [SPEAKER_NAME]
    (subentry_id,) = config_entry.subentries
    registered = entity_registry.async_get(TRACKER)
    assert registered is not None
    assert registered.config_subentry_id == subentry_id
    # As Home Assistant's own Bluetooth trackers
    assert registered.entity_category is EntityCategory.DIAGNOSTIC
    device = device_registry.async_get(str(registered.device_id))
    assert device is not None
    assert (device.name, device.config_subentry_id) == ("Phone", subentry_id)
    state = hass.states.get(TRACKER)
    assert state is not None
    assert (state.state, state.attributes["source_type"]) == (
        STATE_UNKNOWN,
        "bluetooth_le",
    )

    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    assert await scan(hass, config_entry, scans, 30) == STATE_HOME
    scans.heard[SPEAKER] = []
    # The scan that started at 0 was the last to hear it
    assert [await scan(hass, config_entry, scans, now) for now in (60, 90)] == [
        STATE_HOME,
        STATE_NOT_HOME,
    ]

    hass.config_entries.async_remove_subentry(config_entry, subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert runtime(config_entry).bluetooth is None
    assert entity_registry.async_get(TRACKER) is None
    assert hass.states.get(TRACKER) is None


@pytest.mark.usefixtures("google", "replies", "scans")
async def test_tracker_kept_as_google_lists_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    clock: Mock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Keep a tracked device, which Google never lists, however often Google's list is fetched.

    A speaker's device is removed once two home graphs in a row lack it.
    """
    await track_phone(hass, config_entry)
    registered = entity_registry.async_get(TRACKER)
    assert registered is not None

    for fetches in (1, 2, 3):
        await fetch_list(hass, config_entry, clock, fetches)

    assert device_registry.async_get(str(registered.device_id)) is not None
    assert entity_registry.async_get(TRACKER) is not None


@pytest.mark.usefixtures("google", "replies", "scans")
async def test_deleting_tracked_device_stops_tracking(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    entity_registry: er.EntityRegistry,
) -> None:
    """Stop tracking a device deleted from its device page, as deleting it from the integration's page does."""
    await track_phone(hass, config_entry)
    assert await async_setup_component(hass, "config", {})
    registered = entity_registry.async_get(TRACKER)
    assert registered is not None
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "config/device_registry/remove", "device_id": registered.device_id}
    )
    response = await client.receive_json()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert response["success"]
    assert PHONE not in config_entry.subentries
    assert entity_registry.async_get(TRACKER) is None
    # Reloaded with nothing to track, so no more scans
    assert config_entry.state is ConfigEntryState.LOADED
    assert runtime(config_entry).bluetooth is None


async def test_add_device_needs_tracking_on(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Explain that tracking is off instead of adding a device that wouldn't be tracked."""
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"), context={"source": "user"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "bluetooth-tracking-off"


@pytest.mark.parametrize(
    ("user_input", "data"),
    [
        (
            {"name": " Phone ", "irk": base64.b64encode(IRK[::-1]).decode()},
            {"irk": IRK.hex()},
        ),
        ({"name": "Watch", "mac": "aa-bb-cc-dd-ee-ff"}, {"mac": "AA:BB:CC:DD:EE:FF"}),
    ],
)
async def test_add_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_input: dict[str, str],
    data: dict[str, str],
) -> None:
    """Save the IRK as hex in the order the cipher takes, or the normalized MAC."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )

    result = await add_device(hass, config_entry, user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (added,) = config_entry.subentries.values()
    assert (added.title, dict(added.data)) == (user_input["name"].strip(), data)


@pytest.mark.parametrize(
    ("user_input", "errors"),
    [
        ({"name": " ", "irk": IRK.hex()}, {"name": "name-empty"}),
        ({"name": "Phone"}, {"base": "irk-or-mac"}),
        (
            {"name": "Phone", "irk": IRK.hex(), "mac": "AA:BB:CC:DD:EE:FF"},
            {"base": "irk-or-mac"},
        ),
        ({"name": "Phone", "irk": "abc"}, {"irk": "irk-invalid"}),
        ({"name": "Phone", "mac": "abc"}, {"mac": "mac-invalid"}),
        # The same IRK as the tracked phone's, written differently
        (
            {"name": "Phone again", "irk": IRK.hex().upper()},
            {"base": "already-tracked"},
        ),
    ],
)
async def test_add_device_rejects(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_input: dict[str, str],
    errors: dict[str, str],
) -> None:
    """Point out a missing name, a missing or extra identifier, a wrong one, or one already tracked."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))

    result = await add_device(hass, config_entry, user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert list(config_entry.subentries) == [PHONE]


@pytest.mark.usefixtures("google", "replies")
async def test_options_save_bluetooth(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Save Bluetooth tracking and the excluded speakers."""
    await set_up(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"bluetooth_tracking": True, "bluetooth_excluded_speakers": [SPEAKER_ID]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options["bluetooth_tracking"] is True
    assert config_entry.options["bluetooth_excluded_speakers"] == [SPEAKER_ID]


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize(
    ("loaded", "offered"),
    [
        (
            True,
            [
                {"value": "gone", "label": "gone"},
                {"value": SPEAKER_ID, "label": SPEAKER_NAME},
            ],
        ),
        # Google's list is unknown, so only the excluded speakers are offered
        (False, [{"value": "gone", "label": "gone"}]),
    ],
)
async def test_options_offer_speakers_by_name(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    loaded: bool,
    offered: list[dict[str, str]],
) -> None:
    """Offer the speakers by name, keeping excluded ones Google no longer lists."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_excluded_speakers": ["gone"]}
    )
    if loaded:
        await set_up(hass, config_entry)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    schema = result["data_schema"]
    assert schema is not None
    selector = schema.schema["bluetooth_excluded_speakers"]
    assert selector.config["options"] == offered


@pytest.mark.usefixtures("google", "replies", "scans")
async def test_diagnostics_leave_out_tracked_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    """Never show a tracked device's IRK or MAC address in the diagnostics."""
    hass.config_entries.async_add_subentry(
        config_entry,
        subentry({"mac": "AA:BB:CC:DD:EE:FF"}, subentry_id="watch", title="Watch"),
    )
    await track_phone(hass, config_entry)

    diagnostics = json.dumps(
        await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    ).upper()

    assert IRK.hex().upper() not in diagnostics
    assert "AA:BB:CC:DD:EE:FF" not in diagnostics


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
