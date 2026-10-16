"""Tests for how Google Home entities are named."""

from unittest.mock import Mock

import pytest

from custom_components.google_home.number import AlarmVolumeNumber
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeTimersSensor,
)
from custom_components.google_home.switch import DoNotDisturbSwitch

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.helpers.entity_registry import _async_strip_prefix_from_entity_name


@pytest.mark.parametrize(
    "entity_class",
    [
        GoogleHomeAlarmsSensor,
        GoogleHomeTimersSensor,
        GoogleHomeDeviceSensor,
        DoNotDisturbSwitch,
        AlarmVolumeNumber,
    ],
)
def test_entity_name_starts_with_device_name(entity_class: type) -> None:
    """Let Home Assistant strip the device name, so it isn't repeated in entity IDs."""
    entity = entity_class(Mock(), Mock(), "device-id", "Living Room", None)

    assert entity.device_info["name"] == "Living Room"
    # Home Assistant capitalises what's left, which entity IDs lowercase again
    unprefixed = _async_strip_prefix_from_entity_name(entity.name, "Living Room")
    assert unprefixed is not None
    assert unprefixed.casefold() == entity.label.casefold()
