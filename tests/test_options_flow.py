"""Tests for the integration's options, through Home Assistant's flow manager.

The Bluetooth options are tested in test_bluetooth_setup.py.
"""

import pytest
from pytest_homeassistant.common import MockConfigEntry

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .test_config_flow import ENGLISH

# pylint: enable=wrong-import-order


@pytest.mark.parametrize(
    ("options", "interval"), [({}, 15), ({"update_interval": 180}, 180)]
)
async def test_options_show_default_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    options: dict[str, object],
    interval: int,
) -> None:
    """Fill in 15 seconds for an entry without a saved interval, and show it as the default.

    An entry that saved another interval keeps it, and still sees the default below
    the field, not in the label. Home Assistant can't show the text below the field
    without its placeholder's value.
    """
    hass.config_entries.async_update_entry(config_entry, options=options)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    # What the form fills in when nothing is entered
    assert schema({})["update_interval"] == interval
    text = ENGLISH["options"]["step"]["init"]
    placeholders = result["description_placeholders"] or {}
    label = text["data"]["update_interval"].format_map(placeholders)
    below = text["data_description"]["update_interval"].format_map(placeholders)
    assert "Default: 15 seconds" in below
    assert "15" not in label


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Ask for IP addresses, as requests to devices are built from them.

    Then save known hosts without blanks, surrounding spaces and repeats, in order.
    The entry isn't loaded, so the homes aren't offered, and the excluded ones stay
    excluded.
    """
    hass.config_entries.async_update_entry(
        config_entry,
        options={"known_hosts": ["10.0.1.5"], "excluded_homes": ["flat-id"]},
    )
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 180, "known_hosts": ["kitchen.local"]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"known_hosts": "known-host-not-ip"}
    assert config_entry.options == {
        "known_hosts": ["10.0.1.5"],
        "excluded_homes": ["flat-id"],
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "update_interval": 180,
            "known_hosts": [" 10.0.1.5 ", "", "fd00::5", "10.0.1.5"],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "update_interval": 180,
        "known_hosts": ["10.0.1.5", "fd00::5"],
        "bluetooth_tracking": False,
        "bluetooth_excluded_speakers": [],
        "excluded_homes": ["flat-id"],
    }
