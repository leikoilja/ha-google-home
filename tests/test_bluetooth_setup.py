"""Tests for Bluetooth tracking inside Home Assistant.

Home Assistant runs the flows that add tracked devices and change the options, sets
up the entry and keeps its devices. The fixtures in conftest.py fake glocaltokens,
mDNS and the speakers' replies; the scans fixture here fakes their Bluetooth scans,
which the replies table doesn't have.
"""

import base64
from collections.abc import Iterator, Mapping
from datetime import timedelta
from functools import partial
import json
import logging
from typing import cast
from unittest.mock import Mock, patch

from freezegun.api import FrozenDateTimeFactory
import probatio
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.components.recorder.common import async_wait_recording_done
from pytest_homeassistant.typing import ClientSessionGenerator, WebSocketGenerator

from custom_components.google_home import bluetooth as scanner_module
from custom_components.google_home.bluetooth import (
    BluetoothScanError,
    BluetoothScanUnsupported,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY, ConfigEntryState
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from .conftest import SPEAKER_ID, SPEAKER_NAME
from .test_bluetooth import BLUETOOTH, IRK, PHONE, heard, rpa, subentry
from .test_coordinators import runtime
from .test_disabled_devices import kitchen_device, set_disabled
from .test_removed_devices import fetch_list
from .test_setup import set_up
from .test_unsupported_devices import SPEAKER

# pylint: enable=wrong-import-order

TRACKER = "device_tracker.phone"
BEDROOM_NAME = "Bedroom speaker"


class Scans:
    """What each speaker's Bluetooth scans hear, by address, and the clock they read."""

    def __init__(self) -> None:
        """Start with scans that hear nothing, at time 0."""
        self.heard: dict[str, list[BluetoothJsonDict]] = {}
        self.now = 0.0
        # The speakers asked to start a scan, in order
        self.started: list[str] = []
        self.errors: dict[str, BluetoothScanError] = {}

    async def results(
        self, _session: object, device: GoogleHomeDevice
    ) -> list[BluetoothJsonDict]:
        """Return what the speaker heard."""
        if error := self.errors.get(str(device.ip_address)):
            raise error
        return self.heard.get(str(device.ip_address), [])

    async def start(self, _session: object, device: GoogleHomeDevice) -> None:
        """Start a scan."""
        if error := self.errors.get(str(device.ip_address)):
            raise error
        self.started.append(device.name)


@pytest.fixture(name="scans")
def fixture_scans(request: pytest.FixtureRequest) -> Iterator[Scans]:
    """Fake the speakers' Bluetooth scans and the scanner's clock.

    In a test that also freezes time, the freezer starts first, for the reason the
    clock fixture gives.
    """
    if "freezer" in request.fixturenames:
        request.getfixturevalue("freezer")
    scans = Scans()
    wall_origin = dt_util.utcnow().timestamp()
    with (
        patch(f"{BLUETOOTH}.async_get_bluetooth_scan_results", scans.results),
        patch(f"{BLUETOOTH}.async_start_bluetooth_scan", scans.start),
        patch(f"{BLUETOOTH}.monotonic", lambda: scans.now),
        patch(
            "custom_components.google_home.bluetooth_storage.utc_timestamp",
            lambda: wall_origin + scans.now,
        ),
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


@pytest.mark.usefixtures("time_frozen_before")
def test_scans_clock_holds_while_time_is_frozen(
    scans: Scans, freezer: FrozenDateTimeFactory
) -> None:
    """Keep the scanner's time where the test sets it, also while the test freezes time.

    Under pytest -n, whether an earlier test in the same process froze time depends on
    how the tests are shared out.
    """
    scans.now = 5.0
    freezer.tick(timedelta(seconds=60))

    # Through vars(): mypy doesn't count monotonic, imported from time, as the module's
    assert vars(scanner_module)["monotonic"]() == 5.0


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

    result = await add_device(
        hass, config_entry, {"name": "Phone", "irk_or_mac": IRK.hex()}
    )
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
    changes = async_capture_events(hass, EVENT_STATE_CHANGED)
    # The scan that started at 0 was the last to hear it
    assert [await scan(hass, config_entry, scans, now) for now in (60, 90)] == [
        STATE_HOME,
        STATE_NOT_HOME,
    ]
    # Only the change to away, so history gets no row from the update that kept it home
    assert [
        state.state
        for event in changes
        if event.data["entity_id"] == TRACKER and (state := event.data["new_state"])
    ] == [STATE_NOT_HOME]

    hass.config_entries.async_remove_subentry(config_entry, subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert runtime(config_entry).bluetooth is None
    assert entity_registry.async_get(TRACKER) is None
    assert hass.states.get(TRACKER) is None


@pytest.mark.parametrize(
    ("data", "address"),
    [
        ({"irk": IRK.hex()}, rpa(IRK)),
        ({"mac": "AA:BB:CC:DD:EE:FF"}, "AA:BB:CC:DD:EE:FF"),
    ],
    ids=["irk", "mac"],
)
@pytest.mark.usefixtures("google", "replies")
async def test_speakers_shown_but_not_recorded(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    data: dict[str, str],
    address: str,
) -> None:
    """Show the speaker's median RSSI on the tracker, without the address it heard, and keep it out of history.

    RSSI that changes in every scan adds a history row only when a window completes.
    """
    start = dt_util.utcnow()
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(config_entry, subentry(data))
    await set_up(hass, config_entry)

    # Home from 30, so the window runs to 330, hearing it at -50 to -60 dBm
    for now in range(30, 331, 30):
        scans.heard[SPEAKER] = [heard(address, -50 - (now - 30) // 30)]
        assert await scan(hass, config_entry, scans, now) == STATE_HOME

    state = hass.states.get(TRACKER)
    assert state is not None
    assert state.attributes["speakers"] == {SPEAKER_NAME: -55}
    shown = json.dumps(state.attributes).upper()
    assert address.upper() not in shown
    assert IRK.hex().upper() not in shown
    await async_wait_recording_done(hass)
    history = await recorder_mock.async_add_executor_job(
        partial(
            get_significant_states,
            hass,
            start,
            entity_ids=[TRACKER],
            include_start_time_state=False,
            significant_changes_only=False,
        )
    )
    # Unknown at setup, home at 30, and the summary at 330
    assert [
        (recorded.state, "speakers" in recorded.attributes)
        for recorded in cast(list[State], history[TRACKER])
    ] == [(STATE_UNKNOWN, False), (STATE_HOME, False), (STATE_HOME, False)]


@pytest.mark.usefixtures("google", "replies")
async def test_excluded_speaker_not_asked(
    hass: HomeAssistant, config_entry: MockConfigEntry, scans: Scans
) -> None:
    """Never ask a speaker that the options leave out of Bluetooth tracking."""
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "bluetooth_tracking": True,
            "bluetooth_excluded_speakers": [SPEAKER_ID],
        },
    )
    await set_up(hass, config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert runtime(config_entry).bluetooth is not None
    assert scans.started == []


@pytest.mark.usefixtures("two_speakers")
async def test_disabled_speaker_not_asked(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    scans: Scans,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Scan only with the enabled speaker while the other is disabled, also after a restart.

    The disabled speaker no longer keeps the tracker from showing away, and what it
    heard before expires as usual. Enabling it reloads the entry, which scans with it
    again.
    """
    await track_phone(hass, config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    scans.heard[SPEAKER] = [heard(rpa(IRK))]
    assert await scan(hass, config_entry, scans, 30) == STATE_HOME
    kitchen = kitchen_device(device_registry, config_entry)
    await set_disabled(hass, device_registry, kitchen.id, disabled=True)
    scans.started.clear()

    # The scan that started at 0 was the last of the kitchen's that counted
    assert [await scan(hass, config_entry, scans, now) for now in (60, 90)] == [
        STATE_HOME,
        STATE_NOT_HOME,
    ]
    # As at a restart while the kitchen is disabled
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    # At 60 and 90, and at the reload's setup
    assert scans.started == [BEDROOM_NAME] * 3

    scans.started.clear()
    disabled_scanner = runtime(config_entry).bluetooth
    await set_disabled(hass, device_registry, kitchen.id, disabled=False)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert runtime(config_entry).bluetooth is not disabled_scanner
    assert set(scans.started) == {BEDROOM_NAME, SPEAKER_NAME}


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


def reload_reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the debug lines that say why the entry reloads."""
    return [message for message in caplog.messages if message.endswith("reloading...")]


@pytest.mark.usefixtures("google", "replies", "scans")
async def test_log_reload_for_added_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Log that a tracked device was added, not that the options changed."""
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    await set_up(hass, config_entry)

    await add_device(hass, config_entry, {"name": "Phone", "irk_or_mac": IRK.hex()})
    await hass.async_block_till_done(wait_background_tasks=True)

    assert reload_reasons(caplog) == [
        "Bluetooth device added to tracking, reloading..."
    ]


@pytest.mark.usefixtures("google", "replies", "scans")
async def test_log_reload_for_removed_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Log that a tracked device was removed, not that the options changed."""
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    await track_phone(hass, config_entry)

    hass.config_entries.async_remove_subentry(config_entry, PHONE)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert reload_reasons(caplog) == [
        "Bluetooth device removed from tracking, reloading..."
    ]


@pytest.mark.usefixtures("google", "replies", "scans")
async def test_log_reload_for_changed_options(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Log that the Bluetooth options changed when a speaker is left out of tracking."""
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    await track_phone(hass, config_entry)

    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "bluetooth_tracking": True,
            "bluetooth_excluded_speakers": [SPEAKER_ID],
        },
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert reload_reasons(caplog) == ["Bluetooth options changed, reloading..."]


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
    ("value", "data"),
    [
        # As macOS Keychain shows it: base64, in reverse byte order
        (base64.b64encode(IRK[::-1]).decode(), {"irk": IRK.hex()}),
        (IRK.hex().upper(), {"irk": IRK.hex()}),
        (" aa-bb-cc-dd-ee-ff ", {"mac": "AA:BB:CC:DD:EE:FF"}),
        ("AA:BB:CC:DD:EE:0F", {"mac": "AA:BB:CC:DD:EE:0F"}),
    ],
)
async def test_add_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    value: str,
    data: dict[str, str],
) -> None:
    """Tell an IRK from a MAC address in the one field, and save each in its own key.

    The IRK is saved as hex in the order the cipher takes, the MAC address as
    AA:BB:CC:DD:EE:FF, which is what tracking reads.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )

    result = await add_device(
        hass, config_entry, {"name": " Phone ", "irk_or_mac": value}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (added,) = config_entry.subentries.values()
    assert (added.title, dict(added.data)) == ("Phone", data)


@pytest.mark.parametrize(
    ("user_input", "errors"),
    [
        ({"name": " ", "irk_or_mac": IRK.hex()}, {"name": "name-empty"}),
        ({"name": "Phone", "irk_or_mac": " "}, {"irk_or_mac": "irk-or-mac"}),
        # A MAC address needs the same separator between all six pairs
        ({"name": "Tag", "irk_or_mac": "aabbccddeeff"}, {"irk_or_mac": "mac-invalid"}),
        (
            {"name": "Tag", "irk_or_mac": "AA:BB-CC:DD:EE:FF"},
            {"irk_or_mac": "mac-invalid"},
        ),
        (
            {"name": "Tag", "irk_or_mac": "AA:BB:CC:DD:EE"},
            {"irk_or_mac": "mac-invalid"},
        ),
        # Up to 17 characters, the length of a MAC address with separators, is taken
        # as a MAC address, and longer input as an IRK
        (
            {"name": "Tag", "irk_or_mac": "AA:BB:CC:DD:EE:FG"},
            {"irk_or_mac": "mac-invalid"},
        ),
        (
            {"name": "Tag", "irk_or_mac": "AA:BB:CC:DD:EE:FF0"},
            {"irk_or_mac": "irk-invalid"},
        ),
        (
            {"name": "Phone", "irk_or_mac": IRK.hex()[:-1]},
            {"irk_or_mac": "irk-invalid"},
        ),
        # Base64 of 17 bytes, not 16
        (
            {"name": "Phone", "irk_or_mac": base64.b64encode(bytes(17)).decode()},
            {"irk_or_mac": "irk-invalid"},
        ),
        # The same IRK as the tracked phone's, written differently
        (
            {"name": "Phone again", "irk_or_mac": IRK.hex().upper()},
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
    """Point out a missing name or identifier, a wrong one, or one already tracked.

    A name and another device's identifier on the same form then add that device.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))

    result = await add_device(hass, config_entry, user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert list(config_entry.subentries) == [PHONE]

    added = await hass.config_entries.subentries.async_configure(
        str(result["flow_id"]), {"name": "Watch", "irk_or_mac": "AA:BB:CC:DD:EE:FF"}
    )

    assert added["type"] is FlowResultType.CREATE_ENTRY
    assert [
        (tracked.title, dict(tracked.data))
        for tracked in config_entry.subentries.values()
    ] == [("Phone", {"irk": IRK.hex()}), ("Watch", {"mac": "AA:BB:CC:DD:EE:FF"})]


async def test_add_device_logs_no_irk_or_mac(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Never log an IRK or MAC address entered in the form, valid or not."""
    caplog.set_level(logging.DEBUG)
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    entered = [
        base64.b64encode(IRK[::-1]).decode(),
        IRK.hex()[:-1],
        "AA:BB:CC:DD:EE:FF",
        "aabbccddeeff",
    ]

    for value in entered:
        await add_device(hass, config_entry, {"name": "Phone", "irk_or_mac": value})

    assert len(config_entry.subentries) == 2
    logged = caplog.text.upper()
    for value in [*entered, IRK.hex()]:
        assert value.upper() not in logged


@pytest.mark.usefixtures("google", "replies")
async def test_options_save_bluetooth(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Save Bluetooth tracking and the excluded speakers from their section, with the other options."""
    await set_up(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "update_interval": 30,
            "bluetooth": {
                "bluetooth_tracking": True,
                "bluetooth_excluded_speakers": [SPEAKER_ID],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "update_interval": 30,
        "known_hosts": [],
        "bluetooth_tracking": True,
        "bluetooth_excluded_speakers": [SPEAKER_ID],
    }


def bluetooth_section(result: Mapping[str, object]) -> tuple[object, object]:
    """Return the type and default of the form's Bluetooth section, as the frontend gets them.

    The frontend fills a section from the section's default, not from the defaults
    of the fields in it.
    """
    fields = cast(
        list[dict[str, object]],
        probatio.to_field_list(
            result["data_schema"], custom_serializer=cv.custom_serializer
        ),
    )
    (bluetooth,) = (field for field in fields if field["name"] == "bluetooth")
    return bluetooth["type"], bluetooth["default"]


async def test_options_show_saved_bluetooth_options(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Show the saved Bluetooth options in their section when the options open."""
    saved = {"bluetooth_tracking": True, "bluetooth_excluded_speakers": ["gone"]}
    hass.config_entries.async_update_entry(config_entry, options=saved)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert bluetooth_section(result) == ("expandable", saved)


async def test_options_error_keeps_submitted_bluetooth_options(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Show the Bluetooth options just submitted when the form comes back with an error.

    Otherwise the section would show the saved options again, and the next Submit
    would save them, undoing the change.
    """
    hass.config_entries.async_update_entry(
        config_entry,
        options={"bluetooth_tracking": False, "bluetooth_excluded_speakers": ["gone"]},
    )
    submitted = {"bluetooth_tracking": True, "bluetooth_excluded_speakers": []}
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    # An error in another option
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"known_hosts": ["not-an-ip"], "bluetooth": submitted}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"known_hosts": "known-host-not-ip"}
    assert bluetooth_section(result) == ("expandable", submitted)


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
    selector = schema.schema["bluetooth"].schema.schema["bluetooth_excluded_speakers"]
    assert selector.config["options"] == offered


@pytest.mark.usefixtures("google", "replies")
async def test_diagnostics_leave_out_tracked_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    scans: Scans,
) -> None:
    """Leave out subentry contents, credentials and all heard addresses, including untracked ones."""
    mac = "AA:BB:CC:DD:EE:FF"
    address = rpa(IRK)
    unrelated = "02:00:5E:10:20:30"
    title = "Private tracker title"
    credentials = {
        "username": "bluetooth-diagnostics@example.com",
        "password": "invented-bluetooth-password",
        "master_token": "aas_et/" + "s" * 216,
        "android_id": "a9b8c7d6e5f40312",
    }
    hass.config_entries.async_update_entry(config_entry, data=credentials)
    hass.config_entries.async_add_subentry(
        config_entry,
        subentry(
            {"mac": mac, "private": "invented-subentry-secret"},
            subentry_id="watch",
            title=title,
        ),
    )
    await track_phone(hass, config_entry)
    scans.heard[SPEAKER] = [heard(address), heard(mac), heard(unrelated)]
    assert await scan(hass, config_entry, scans, 30) == STATE_HOME

    downloaded = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    diagnostics = json.dumps(downloaded).upper()

    secrets = [
        IRK.hex(),
        base64.b64encode(IRK[::-1]).decode(),
        mac,
        address,
        unrelated,
        title,
        "invented-subentry-secret",
        *credentials.values(),
        *[
            device.auth_token
            for device in runtime(config_entry).client.google_devices
            if device.auth_token
        ],
    ]
    assert [value for value in secrets if value.upper() in diagnostics] == []
    bluetooth = cast(dict[str, object], downloaded["bluetooth"])
    assert bluetooth["trackers"] == {
        PHONE: {"state": "home"},
        "watch": {"state": "home"},
    }


@pytest.mark.usefixtures("google", "replies", "scans")
@pytest.mark.parametrize("tracking", [False, True])
async def test_diagnostics_without_active_bluetooth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    tracking: bool,
) -> None:
    """No active summary when tracking is off, or on without devices to track."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": tracking}
    )
    if not tracking:
        hass.config_entries.async_add_subentry(
            config_entry, subentry({"irk": IRK.hex()})
        )
    await set_up(hass, config_entry)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    assert diagnostics["bluetooth"] is None


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.freeze_time("2026-10-15 12:00:00+00:00")
@pytest.mark.parametrize(
    (
        "status",
        "excluded",
        "unsupported",
        "answered",
        "covers",
        "covered_until",
        "state",
    ),
    [
        ("excluded", True, False, False, False, None, "unknown"),
        ("unsupported", False, True, False, False, None, "unknown"),
        ("never-answered", False, False, False, False, None, "unknown"),
        ("starting", False, False, False, False, None, "unknown"),
        ("covering", False, False, True, True, "2026-10-15T05:00:00-07:00", "not_home"),
        (
            "blocking",
            False,
            False,
            True,
            False,
            "2026-10-15T04:59:30-07:00",
            "not_home",
        ),
        ("became-unsupported", False, True, True, False, None, "not_home"),
        ("disabled", True, False, True, False, None, "not_home"),
    ],
)
async def test_diagnostics_bluetooth_speakers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    scans: Scans,
    device_registry: dr.DeviceRegistry,
    status: str,
    excluded: bool,
    unsupported: bool,
    answered: bool,
    covers: bool,
    covered_until: str | None,
    state: str,
) -> None:
    """Show allowlisted scan facts, preserving answered-ever after failures or a 404."""
    error_text = f"private error at {SPEAKER} with invented-token"
    if status == "unsupported":
        scans.errors[SPEAKER] = BluetoothScanUnsupported(error_text)
    elif status == "never-answered":
        scans.errors[SPEAKER] = BluetoothScanError(error_text)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "bluetooth_tracking": True,
            "bluetooth_excluded_speakers": [SPEAKER_ID] if status == "excluded" else [],
        },
    )
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))
    await set_up(hass, config_entry)
    if status != "starting":
        for now in range(30, 121, 30):
            await scan(hass, config_entry, scans, now)
    if status in {"blocking", "became-unsupported"}:
        scans.errors[SPEAKER] = (
            BluetoothScanUnsupported(error_text)
            if unsupported
            else BluetoothScanError(error_text)
        )
        await scan(hass, config_entry, scans, 150)
    if status == "disabled":
        device = kitchen_device(device_registry, config_entry)
        await set_disabled(hass, device_registry, device.id, disabled=True)
        await scan(hass, config_entry, scans, 150)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    assert diagnostics["bluetooth"] == {
        "speakers": {
            SPEAKER_ID: {
                "participating": status in {"covering", "blocking"},
                "last_success_age": 30.0
                if status == "blocking"
                else 0.0
                if status == "covering"
                else None,
                "remaining_lease": 270.0
                if status == "blocking"
                else 300.0
                if status == "covering"
                else None,
                "excluded": excluded,
                "unsupported": unsupported,
                "answered": answered,
                "covers_presence_window": covers,
                "covered_until": covered_until,
            }
        },
        "trackers": {PHONE: {"state": state}},
    }
    assert error_text not in json.dumps(diagnostics)


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize(
    "covered_until",
    [
        pytest.param(
            "2026-10-15T04:59:55-07:00",
            marks=pytest.mark.freeze_time("2026-10-15 12:00:00+00:00"),
            id="ordinary-time",
        ),
        pytest.param(
            "2026-11-01T01:59:58-07:00",
            marks=pytest.mark.freeze_time("2026-11-01 09:00:03+00:00"),
            id="daylight-saving-fallback",
        ),
    ],
)
async def test_diagnostics_coverage_expires_between_updates(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    scans: Scans,
    covered_until: str,
) -> None:
    """Coverage uses download time, and its endpoint is the scan end, not the later read."""
    await track_phone(hass, config_entry)
    for now in (35, 65, 95, 125):
        await scan(hass, config_entry, scans, now)
    # Read the next scan late: it covers only 30 seconds from 125, not until 160.
    await scan(hass, config_entry, scans, 160)
    delayed = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    bluetooth = cast(dict[str, dict[str, dict[str, object]]], delayed["bluetooth"])
    assert bluetooth["speakers"][SPEAKER_ID]["covered_until"] == covered_until
    # Coverage through 155 stays fresh for 45s, even without another refresh.
    scans.now = 200
    fresh = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    scans.now = 200.001
    expired = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    fresh_bluetooth = cast(dict[str, dict[str, dict[str, object]]], fresh["bluetooth"])
    expired_bluetooth = cast(
        dict[str, dict[str, dict[str, object]]], expired["bluetooth"]
    )
    assert fresh_bluetooth["speakers"][SPEAKER_ID]["covers_presence_window"] is True
    assert expired_bluetooth["speakers"][SPEAKER_ID]["covers_presence_window"] is False


@pytest.mark.usefixtures("google", "replies")
async def test_diagnostics_use_latest_tracker_update(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    scans: Scans,
) -> None:
    """Show unavailable from the latest update even while the scanner remembers away."""
    await track_phone(hass, config_entry)
    for now in range(30, 121, 30):
        assert await scan(hass, config_entry, scans, now) in {
            STATE_UNKNOWN,
            STATE_NOT_HOME,
        }
    scans.errors[SPEAKER] = BluetoothScanError("invented private error")
    assert await scan(hass, config_entry, scans, 420) == "unavailable"

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    bluetooth = cast(dict[str, object], diagnostics["bluetooth"])
    assert bluetooth["trackers"] == {PHONE: {"state": "unavailable"}}
