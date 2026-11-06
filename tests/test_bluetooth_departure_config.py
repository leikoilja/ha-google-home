"""Real HA config-flow validation for each Bluetooth tracker's optional delay."""

import math
from typing import cast
from unittest.mock import patch

import probatio
import pytest
from pytest_homeassistant.common import MockConfigEntry

# pylint: disable=wrong-import-order
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.translation import async_get_translations

from .test_bluetooth import IRK, PHONE, subentry

# pylint: enable=wrong-import-order

RADIO_SELECTOR = {
    "select": {
        "options": [
            {"value": "0", "label": "0 s"},
            {"value": "30", "label": "30 s"},
            {"value": "60", "label": "60 s"},
            {"value": "90", "label": "90 s"},
            {"value": "120", "label": "120 s"},
        ],
        "multiple": False,
        "custom_value": False,
        "mode": "list",
        "translation_key": "departure_delay",
        "sort": False,
    }
}


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
    assert fields[-1]["selector"] == RADIO_SELECTOR
    assert fields[-1]["default"] == "0"
    await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Tag",
            "irk_or_mac": "aa-bb-cc-dd-ee-ff",
            "additional_departure_delay": str(delay),
        },
    )
    (added,) = config_entry.subentries.values()
    assert added.data["mac"] == "AA:BB:CC:DD:EE:FF"
    assert added.data.get("additional_departure_delay", 0) == delay
    if delay:
        assert isinstance(added.data["additional_departure_delay"], int)
    else:
        assert "additional_departure_delay" not in added.data


@pytest.mark.parametrize("stored_delay", [None, 0, 30, 60, 90, 120])
async def test_reconfigure_only_departure_delay(
    hass: HomeAssistant, config_entry: MockConfigEntry, stored_delay: int | None
) -> None:
    """Editing timing while tracking is off retains identity and other data."""
    data: dict[str, str | int] = {"irk": IRK.hex(), "other": "keep"}
    if stored_delay is not None:
        data["additional_departure_delay"] = stored_delay
    tracked = subentry(data)
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
    assert fields[0]["selector"] == RADIO_SELECTOR
    assert fields[0]["default"] == str(stored_delay or 0)
    saved = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"additional_departure_delay": "30"}
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
    "value",
    [
        False,
        True,
        None,
        30,
        30.0,
        -30,
        150,
        math.nan,
        math.inf,
        "15",
        "30.5",
        "150",
        "",
        "030",
        [],
        {},
    ],
)
async def test_departure_delay_schema_refusal(
    hass: HomeAssistant, config_entry: MockConfigEntry, source: str, value: object
) -> None:
    """Only the five string selections can pass either real HA form's schema."""
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
    with pytest.raises(InvalidData) as refused:
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], submitted
        )
    assert refused.value.schema_errors == {
        "additional_departure_delay": "departure-delay-invalid"
    }
    assert {
        key: dict(item.data) for key, item in config_entry.subentries.items()
    } == before


async def test_departure_radio_labels(hass: HomeAssistant) -> None:
    """Only normal timing needs translation; numeric labels come from the policy."""
    text = await async_get_translations(hass, "en", "selector", ["google_home"])
    assert text == {
        "component.google_home.selector.departure_delay.options.0": "Normal timing",
    }


@pytest.mark.parametrize("source", ["user", "reconfigure"])
async def test_policy_values_feed_bluetooth_form(
    hass: HomeAssistant, config_entry: MockConfigEntry, source: str
) -> None:
    """A policy edit reaches both help text and valid choices without locale edits."""
    hass.config_entries.async_update_entry(
        config_entry, options={"bluetooth_tracking": True}
    )
    if source == "reconfigure":
        hass.config_entries.async_add_subentry(
            config_entry, subentry({"irk": IRK.hex()})
        )
    # Invented presentation policy, not a new supported production setting.
    with patch.multiple(
        "custom_components.google_home.config_flow",
        BLUETOOTH_PRESENCE_WINDOW=75,
        DEPARTURE_DELAY_VALUES=(0, 45, 105),
    ):
        result = await hass.config_entries.subentries.async_init(
            (config_entry.entry_id, "bluetooth_device"),
            context={"source": source, "subentry_id": PHONE},
        )
        fields = cast(
            list[dict[str, object]],
            probatio.to_field_list(
                result["data_schema"], custom_serializer=cv.custom_serializer
            ),
        )
        assert fields[-1]["selector"] == {
            "select": {
                **RADIO_SELECTOR["select"],
                "options": [
                    {"value": "0", "label": "0 s"},
                    {"value": "45", "label": "45 s"},
                    {"value": "105", "label": "105 s"},
                ],
            }
        }
        text = await async_get_translations(
            hass, "en", "config_subentries", ["google_home"]
        )
        step = "user" if source == "user" else "reconfigure"
        prefix = f"component.google_home.config_subentries.bluetooth_device.step.{step}"
        help_text = text[f"{prefix}.data_description.additional_departure_delay"]
        placeholders = result["description_placeholders"]
        assert placeholders is not None
        assert placeholders["presence_window"] == "75"
        assert "75-second" in help_text.format(**placeholders)
        if source == "user":
            assert placeholders["irk_bytes"] == "16"
            assert placeholders["irk_hex_length"] == "32"
            assert text[f"{prefix}.data_description.irk_or_mac"] == (
                "A phone's Identity Resolving Key, as {irk_hex_length} hex digits or "
                "in base64, or a MAC address such as AA:BB:CC:DD:EE:FF."
            )
        submitted = {"additional_departure_delay": "45"}
        if source == "user":
            submitted |= {"name": "Tag", "irk_or_mac": "AA:BB:CC:DD:EE:FF"}
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], submitted
        )
        (tracked,) = config_entry.subentries.values()
        assert tracked.data["additional_departure_delay"] == 45
        assert isinstance(tracked.data["additional_departure_delay"], int)


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
            "additional_departure_delay": "120",
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
        result["flow_id"], {"additional_departure_delay": "30"}
    )
    assert refused["type"] is FlowResultType.ABORT
    assert refused["reason"] == "device-removed"
    assert not config_entry.subentries
