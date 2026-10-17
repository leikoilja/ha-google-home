"""Tests for Bluetooth presence tracking."""

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
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.bluetooth import (
    BluetoothScanner,
    TrackedDevice,
    TrackerState,
    normalize_mac,
    parse_irk,
)
from custom_components.google_home.config_flow import (
    BluetoothDeviceSubentryFlow,
    GoogleHomeOptionsFlowHandler,
)
from custom_components.google_home.const import (
    DATA_BLUETOOTH_CONFIG,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
)
from custom_components.google_home.device_tracker import GoogleHomeBluetoothTracker
from custom_components.google_home.exceptions import (
    BluetoothScanError,
    BluetoothScanUnsupported,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.config_entries import ConfigSubentry

# glocaltokens accepts only master tokens of the real length
MASTER_TOKEN = "aas_et/" + "x" * 216
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
    """Fake speakers that answer the client's Bluetooth requests."""

    def __init__(self, *names: str) -> None:
        """Create speakers with addresses and tokens."""
        self.devices = [
            GoogleHomeDevice(name.lower(), name, "token", ip_address=f"10.0.0.{i}")
            for i, name in enumerate(names, 1)
        ]
        self.now = 0.0
        # What each speaker's scan results hold, by device ID
        self.results: dict[str, list[BluetoothJsonDict]] = {}
        self.failing: set[str] = set()
        self.failing_start: set[str] = set()
        self.unsupported: set[str] = set()
        self.reads: list[str] = []
        self.starts: list[str] = []

    async def async_get_bluetooth_scan_results(
        self, device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        """Return what the speaker heard."""
        self._raise_if_failing(device)
        self.reads.append(device.device_id)
        return self.results.get(device.device_id, [])

    async def async_start_bluetooth_scan(self, device: GoogleHomeDevice) -> None:
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
    """Return a scanner using the fake speakers and their clock."""
    return BluetoothScanner(
        Mock(
            async_get_bluetooth_scan_results=speakers.async_get_bluetooth_scan_results,
            async_start_bluetooth_scan=speakers.async_start_bluetooth_scan,
        ),
        Mock(data=speakers.devices),
        tracked or [subentry({"irk": IRK.hex()})],
        excluded or [],
        clock=lambda: speakers.now,
    )


def update(scanner: BluetoothScanner, speakers: Speakers, now: float) -> TrackerState:
    """Run an update at a time and return the phone's state."""
    speakers.now = now
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
    # The old results hold the phone, but aren't read
    speakers.results["kitchen"] = [heard(rpa(IRK))]
    speakers.reads.clear()
    assert update(scanner, speakers, 150) == UNAVAILABLE
    assert not speakers.reads


def test_recover_after_failed_scan_start() -> None:
    """Confirm away again 120 seconds after a scan failed to start."""
    speakers = Speakers("Kitchen")
    scanner = make_scanner(speakers)
    states(scanner, speakers, range(0, 120, 30))

    speakers.failing_start.add("kitchen")
    update(scanner, speakers, 120)
    speakers.failing_start.clear()

    assert states(scanner, speakers, range(150, 270, 30)) == [
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
    # The update after 90 is delayed until 300
    assert update(scanner, speakers, 300) == UNAVAILABLE
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
    """Show unavailable, not away, when the speaker that heard the phone stops answering."""
    speakers = Speakers("Bedroom", "Kitchen")
    speakers.results["bedroom"] = [heard(rpa(IRK))]
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 90, 30)) == [UNKNOWN, HOME, HOME]

    # The last bedroom scan to hear it started at 30; the kitchen hears nothing
    speakers.failing.add("bedroom")
    assert states(scanner, speakers, range(90, 600, 30)) == [HOME] + [UNAVAILABLE] * 16


def test_new_speaker_must_cover_the_window() -> None:
    """Wait for a speaker found later to scan for the whole window before away."""
    speakers = Speakers("Kitchen")
    bedroom = GoogleHomeDevice("bedroom", "Bedroom", "token")
    speakers.devices.append(bedroom)
    scanner = make_scanner(speakers)
    assert states(scanner, speakers, range(0, 120, 30))[-1] == NOT_HOME

    bedroom.ip_address = "10.0.0.9"
    assert states(scanner, speakers, range(120, 240, 30)) == [
        UNAVAILABLE,
        UNAVAILABLE,
        UNAVAILABLE,
        NOT_HOME,
    ]


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
    speakers.failing.add("garage")
    scanner = make_scanner(speakers)

    with caplog.at_level(logging.WARNING):
        states(scanner, speakers, range(0, 300, 30))
        assert not caplog.records
        states(scanner, speakers, range(300, 600, 30))

    assert len(caplog.records) == 1
    assert "Garage" in caplog.text


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

    assert async_create_bluetooth_coordinator(Mock(), entry, Mock(), Mock()) is None


def test_scanner_never_raises() -> None:
    """Never fail an update, so Bluetooth can't fail or delay setup."""
    speakers = Speakers("Kitchen")
    speakers.failing.add("kitchen")
    scanner = make_scanner(speakers)

    assert states(scanner, speakers, range(0, 60, 30)) == [UNKNOWN, UNKNOWN]


def run_update_listener(entry: Mock, setup_entry: Mock) -> Mock:
    """Run the update listener after the entry changed and return Home Assistant."""
    hass = Mock()
    hass.data = {
        DOMAIN: {
            "entry": {
                DATA_CLIENT: Mock(known_hosts=[]),
                DATA_COORDINATOR: Mock(),
                DATA_BLUETOOTH_CONFIG: bluetooth_config(setup_entry),
            }
        }
    }
    asyncio.run(async_update_entry(hass, entry))
    return hass


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # Adding the first tracked device starts scanning
        (make_entry({"bluetooth_tracking": True}), [subentry({"irk": IRK.hex()})]),
        # Removing the last one stops it
        (
            make_entry({"bluetooth_tracking": True}, [subentry({"irk": IRK.hex()})]),
            [],
        ),
    ],
)
def test_reload_when_tracked_devices_change(
    before: Mock, after: list[ConfigSubentry]
) -> None:
    """Reload when a tracked device is added or removed."""
    entry = make_entry({"bluetooth_tracking": True}, after)

    hass = run_update_listener(entry, before)

    hass.config_entries.async_schedule_reload.assert_called_once_with("entry")


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


def make_options_flow(
    options: dict[str, object], devices: list[GoogleHomeDevice]
) -> GoogleHomeOptionsFlowHandler:
    """Return the options flow of a loaded entry with these devices."""
    flow = GoogleHomeOptionsFlowHandler()
    flow.hass = Mock()
    flow.hass.config_entries.async_get_known_entry.return_value = Mock(
        entry_id="entry", options=options
    )
    flow.hass.data = {DOMAIN: {"entry": {DATA_COORDINATOR: Mock(data=devices)}}}
    flow.handler = "entry"
    return flow


def test_options_save_bluetooth() -> None:
    """Save Bluetooth tracking and the excluded speakers."""
    flow = make_options_flow({}, [])

    result = asyncio.run(
        flow.async_step_init(
            {
                "update_interval": 180,
                "bluetooth_tracking": True,
                "bluetooth_excluded_speakers": ["garage"],
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["data"]["bluetooth_tracking"] is True
    assert result["data"]["bluetooth_excluded_speakers"] == ["garage"]


def test_options_offer_speakers_by_name() -> None:
    """Offer the speakers by name, keeping excluded ones Google no longer lists."""
    flow = make_options_flow(
        {"bluetooth_excluded_speakers": ["gone"]},
        [GoogleHomeDevice("kitchen", "Kitchen", "token")],
    )

    result = asyncio.run(flow.async_step_init())

    schema = result["data_schema"]
    assert schema is not None
    selector = schema.schema["bluetooth_excluded_speakers"]
    assert selector.config["options"] == [
        {"value": "gone", "label": "gone"},
        {"value": "kitchen", "label": "Kitchen"},
    ]


def make_subentry_flow(
    options: dict[str, object], subentries: list[ConfigSubentry] | None = None
) -> BluetoothDeviceSubentryFlow:
    """Return the flow that adds a tracked device to an entry."""
    flow = BluetoothDeviceSubentryFlow()
    flow.hass = Mock()
    flow.handler = ("entry", "bluetooth_device")
    flow.context = {"source": "user"}
    flow._get_entry = Mock(  # type: ignore[method-assign]  # noqa: SLF001  # pylint: disable=protected-access
        return_value=make_entry(options, subentries)
    )
    return flow


def add_device(
    user_input: dict[str, str], subentries: list[ConfigSubentry] | None = None
) -> dict[str, object]:
    """Submit the form that adds a tracked device, with tracking on."""
    flow = make_subentry_flow({"bluetooth_tracking": True}, subentries)
    return dict(asyncio.run(flow.async_step_user(user_input)))


def test_add_device_needs_tracking_on() -> None:
    """Explain that tracking is off instead of adding a device that wouldn't be tracked."""
    flow = make_subentry_flow({})

    result = asyncio.run(flow.async_step_user())

    assert result["type"] == "abort"
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
def test_add_device(user_input: dict[str, str], data: dict[str, str]) -> None:
    """Save the IRK as hex in the order the cipher takes, or the normalized MAC."""
    result = add_device(user_input)

    assert result["type"] == "create_entry"
    assert result["title"] == user_input["name"].strip()
    assert result["data"] == data


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
    ],
)
def test_add_device_rejects(user_input: dict[str, str], errors: dict[str, str]) -> None:
    """Point out a missing name, a missing or extra identifier, or a wrong one."""
    result = add_device(user_input)

    assert result["type"] == "form"
    assert result["errors"] == errors


def test_add_device_rejects_duplicate() -> None:
    """Refuse to track the same IRK twice."""
    result = add_device(
        {"name": "Phone again", "irk": IRK.hex().upper()},
        [subentry({"irk": IRK.hex()})],
    )

    assert result["errors"] == {"base": "already-tracked"}


def api_client(
    status: int = 200, body: object = None
) -> tuple[GlocaltokensApiClient, Mock]:
    """Return an API client whose device answers with this status and JSON body."""
    response = MagicMock()
    response.__aenter__.return_value = Mock(
        status=status, json=AsyncMock(return_value=body)
    )
    session = Mock(request=Mock(return_value=response))
    return GlocaltokensApiClient(Mock(), session, master_token=MASTER_TOKEN), session


KITCHEN = GoogleHomeDevice("kitchen", "Kitchen", "token", ip_address="10.0.0.1")


def test_start_scan_request() -> None:
    """Start a 30-second scan that clears the previous results."""
    client, session = api_client()

    asyncio.run(client.async_start_bluetooth_scan(KITCHEN))

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
    client, _session = api_client(
        body=[
            {"mac_address": "AA:BB:CC:DD:EE:FF", "rssi": -50, "name": ""},
            {"mac_address": "AA:BB:CC:DD:EE:00"},
            "garbage",
        ]
    )

    results = asyncio.run(client.async_get_bluetooth_scan_results(KITCHEN))

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
    client, _session = api_client(status, body)

    with pytest.raises(error):
        asyncio.run(client.async_get_bluetooth_scan_results(KITCHEN))


def test_request_failure_leaves_device_available() -> None:
    """Raise on a connection error without marking the device unavailable."""
    client, session = api_client()
    session.request.side_effect = ClientError("offline")
    device = GoogleHomeDevice("kitchen", "Kitchen", "token", ip_address="10.0.0.1")

    with pytest.raises(BluetoothScanError):
        asyncio.run(client.async_start_bluetooth_scan(device))
    assert device.available
