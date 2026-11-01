"""Tests for Bluetooth tracking inside Home Assistant.

Home Assistant runs the flows that add tracked devices and change the options, sets
up the entry and keeps its devices. The fixtures in conftest.py fake glocaltokens,
mDNS and the speakers' replies; the scans fixture here fakes their Bluetooth scans,
which the replies table doesn't have.
"""

import base64
from collections.abc import Iterator, Mapping
import json
import logging
from typing import cast
from unittest.mock import Mock, patch

import probatio
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_capture_events
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator, WebSocketGenerator

from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import BluetoothJsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.setup import async_setup_component

from .conftest import SPEAKER_ID, SPEAKER_NAME
from .test_bluetooth import BLUETOOTH, IRK, PHONE, heard, rpa, subentry
from .test_coordinators import runtime
from .test_removed_devices import fetch_list
from .test_setup import set_up
from .test_unsupported_devices import SPEAKER

# pylint: enable=wrong-import-order

TRACKER = "device_tracker.phone"


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
    """Point out a missing name or identifier, a wrong one, or one already tracked."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))

    result = await add_device(hass, config_entry, user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert list(config_entry.subentries) == [PHONE]


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
