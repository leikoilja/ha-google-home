"""Tests for how Google Home entities are named and when they are available."""

from unittest.mock import Mock

import pytest

from custom_components.google_home.button import RebootButton
from custom_components.google_home.models import GoogleHomeDevice
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
        RebootButton,
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


@pytest.mark.parametrize(
    "entity_class",
    [
        GoogleHomeAlarmsSensor,
        GoogleHomeTimersSensor,
        GoogleHomeDeviceSensor,
        DoNotDisturbSwitch,
        AlarmVolumeNumber,
        RebootButton,
    ],
)
def test_entity_unavailable_when_google_no_longer_lists_device(
    entity_class: type,
) -> None:
    """Show every entity of a device removed in the Google Home app as unavailable.

    Otherwise the switch would show off and the alarm volume 0.
    """
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "10.0.0.2")
    coordinator = Mock(data=[device], last_update_success=True)
    entity = entity_class(coordinator, Mock(), "device-id", "Kitchen", None)
    assert entity.available

    coordinator.data = []

    assert not entity.available


def test_unique_id_ignores_device_name() -> None:
    """Keep entity IDs when a device's name changes, as they follow the unique ID."""
    before = GoogleHomeAlarmsSensor(Mock(), Mock(), "pair", "Den speaker left", None)
    after = GoogleHomeAlarmsSensor(Mock(), Mock(), "pair", "Den speakers", None)

    assert before.unique_id == after.unique_id == "pair/alarms"
