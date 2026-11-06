"""Real HA config-flow validation for each Bluetooth tracker's optional delay."""

import math
from typing import cast

import probatio
import pytest
from pytest_homeassistant.common import MockConfigEntry

# pylint: disable=wrong-import-order
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv

from .test_bluetooth import IRK, PHONE, subentry

# pylint: enable=wrong-import-order


@pytest.mark.parametrize("delay", [0, 30, 60, 90, 120])
async def test_add_device_departure_delay(
    hass: HomeAssistant, config_entry: MockConfigEntry, delay: int
) -> None:
    """Save optional timing without changing normalized matching credentials."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"), context={"source": "user"}
    )
    fields = cast(
        list[dict[str, object]],
        probatio.to_field_list(
            result["data_schema"], custom_serializer=cv.custom_serializer
        ),
    )
    assert fields[-1]["selector"] == {
        "number": {
            "min": 0,
            "max": 120,
            "step": 30,
            "mode": "box",
            "unit_of_measurement": "s",
        }
    }
    await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Tag",
            "irk_or_mac": "aa-bb-cc-dd-ee-ff",
            "additional_departure_delay": delay,
        },
    )
    (added,) = config_entry.subentries.values()
    assert added.data["mac"] == "AA:BB:CC:DD:EE:FF"
    assert added.data.get("additional_departure_delay", 0) == delay


async def test_reconfigure_only_departure_delay(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Editing timing while tracking is off retains identity and other data."""
    tracked = subentry({"irk": IRK.hex(), "other": "keep"})
    hass.config_entries.async_add_subentry(config_entry, tracked)
    options = dict(config_entry.options)
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"),
        context={"source": "reconfigure", "subentry_id": PHONE},
    )
    fields = cast(
        list[dict[str, object]],
        probatio.to_field_list(
            result["data_schema"], custom_serializer=cv.custom_serializer
        ),
    )
    assert [field["name"] for field in fields] == ["additional_departure_delay"]
    assert fields[0]["default"] == 0
    saved = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"additional_departure_delay": 30.0}
    )
    assert saved["type"] is FlowResultType.ABORT
    assert saved["reason"] == "reconfigure_successful"
    assert config_entry.subentries[PHONE] is tracked
    assert dict(tracked.data) == {
        "irk": IRK.hex(),
        "other": "keep",
        "additional_departure_delay": 30,
    }
    assert isinstance(tracked.data["additional_departure_delay"], int)
    assert dict(config_entry.options) == options


@pytest.mark.parametrize("source", ["user", "reconfigure"])
@pytest.mark.parametrize(
    "value", [False, True, None, "30", -30, 150, math.nan, math.inf]
)
async def test_departure_delay_schema_refusal(
    hass: HomeAssistant, config_entry: MockConfigEntry, source: str, value: object
) -> None:
    """The real flow rejects raw booleans before the number selector loses their type."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))
    before = {key: dict(item.data) for key, item in config_entry.subentries.items()}
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"),
        context={"source": source, "subentry_id": PHONE},
    )
    submitted = {"additional_departure_delay": value}
    if source == "user":
        submitted |= {"name": "Tag", "irk_or_mac": "AA:BB:CC:DD:EE:FF"}
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], submitted
        )
    assert {
        key: dict(item.data) for key, item in config_entry.subentries.items()
    } == before


@pytest.mark.parametrize("source", ["user", "reconfigure"])
@pytest.mark.parametrize("value", [15, 30.5])
async def test_departure_delay_increment_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, source: str, value: float
) -> None:
    """In-range disallowed steps reach the integration's translated field error."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"),
        context={"source": source, "subentry_id": PHONE},
    )
    submitted: dict[str, object] = {"additional_departure_delay": value}
    if source == "user":
        submitted |= {"name": "Tag", "irk_or_mac": "AA:BB:CC:DD:EE:FF"}
    refused = await hass.config_entries.subentries.async_configure(
        result["flow_id"], submitted
    )
    assert refused["type"] is FlowResultType.FORM
    assert refused["errors"] == {
        "additional_departure_delay": "departure-delay-invalid"
    }
    assert "additional_departure_delay" not in config_entry.subentries[PHONE].data
    assert list(config_entry.subentries) == [PHONE]


@pytest.mark.parametrize("data", [{"irk": IRK.hex()}, {"mac": "AA:BB:CC:DD:EE:FF"}])
async def test_duplicate_identity_ignores_departure_delay(
    hass: HomeAssistant, config_entry: MockConfigEntry, data: dict[str, str]
) -> None:
    """Different delay settings cannot bypass duplicate matching."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    hass.config_entries.async_add_subentry(
        config_entry, subentry({**data, "additional_departure_delay": 60})
    )
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"), context={"source": "user"}
    )
    refused = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Duplicate",
            "irk_or_mac": next(iter(data.values())),
            "additional_departure_delay": 120,
        },
    )
    assert refused["errors"] == {"base": "already-tracked"}
    assert list(config_entry.subentries) == [PHONE]


async def test_reconfigure_removed_tracker(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A late submission cannot recreate a removed tracker."""
    hass.config_entries.async_add_subentry(config_entry, subentry({"irk": IRK.hex()}))
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, "bluetooth_device"),
        context={"source": "reconfigure", "subentry_id": PHONE},
    )
    hass.config_entries.async_remove_subentry(config_entry, PHONE)
    refused = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"additional_departure_delay": 30}
    )
    assert refused["type"] is FlowResultType.ABORT
    assert refused["reason"] == "device-removed"
    assert not config_entry.subentries
