"""Tests for devices that the user disabled in Home Assistant, running inside Home Assistant.

As in test_coordinators, only glocaltokens, mDNS and the speakers' answers are faked.
A disabled device is asked nothing until it's enabled again, and Home Assistant then
reloads the entry. It stays in Google's list handling meanwhile.
"""

from datetime import timedelta
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import DOMAIN

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import BEDROOM, BEDROOM_ID, SPEAKER_ID, kitchen_speaker
from .test_coordinators import (
    BEDROOM_ALARMS,
    EVERYTHING,
    KITCHEN_ALARMS,
    asked,
    asked_by,
)
from .test_removed_devices import bedroom_device, fetch_list
from .test_setup import set_up, state
from .test_unsupported_devices import ALARMS, SPEAKER

# pylint: enable=wrong-import-order


def kitchen_device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry
) -> dr.DeviceEntry:
    """Return the entry's device of the kitchen speaker."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SPEAKER_ID), entry.entry_id
    )
    assert device is not None
    return device


async def set_disabled(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    device_id: str,
    *,
    disabled: bool,
) -> None:
    """Disable or enable a device as its page in Home Assistant does."""
    device_registry.async_update_device(
        device_id, disabled_by=dr.DeviceEntryDisabler.USER if disabled else None
    )
    await hass.async_block_till_done()


async def run_updates(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int
) -> None:
    """Let the scheduled updates of the next seconds run, 15 seconds at a time."""
    for _ in range(seconds // 15):
        freezer.tick(timedelta(seconds=15))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.usefixtures("two_speakers")
async def test_disabled_speaker_not_asked(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask a speaker nothing once it's disabled, at scheduled updates or a refresh of all devices.

    The other speaker is still updated at each, and the disabled one stays.
    """
    await set_up(hass, config_entry)
    kitchen = kitchen_device(device_registry, config_entry)
    await set_disabled(hass, device_registry, kitchen.id, disabled=True)
    asked(aioclient_mock)

    await run_updates(hass, freezer, 60)
    requests = asked(aioclient_mock)
    await hass.services.async_call(
        DOMAIN, "refresh_devices", {ATTR_ENTITY_ID: BEDROOM_ALARMS}, blocking=True
    )
    await hass.async_block_till_done()

    # One update every 15 seconds
    assert asked_by(requests, BEDROOM) == EVERYTHING * 4
    assert asked_by(requests, SPEAKER) == []
    requests = asked(aioclient_mock)
    assert asked_by(requests, BEDROOM) == EVERYTHING
    assert asked_by(requests, SPEAKER) == []
    assert kitchen_device(device_registry, config_entry).disabled


@pytest.mark.usefixtures("two_speakers")
async def test_speaker_disabled_before_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask a speaker that was disabled before the entry loads nothing at setup or later.

    As when Home Assistant restarts while it's disabled.
    """
    await set_up(hass, config_entry)
    kitchen = kitchen_device(device_registry, config_entry)
    await set_disabled(hass, device_registry, kitchen.id, disabled=True)
    asked(aioclient_mock)

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    at_setup = asked(aioclient_mock)
    await run_updates(hass, freezer, 30)
    later = asked(aioclient_mock)

    assert ALARMS in asked_by(at_setup, BEDROOM)
    assert asked_by(later, BEDROOM) == EVERYTHING * 2
    assert asked_by(at_setup + later, SPEAKER) == []
    assert hass.states.get(KITCHEN_ALARMS) is None


@pytest.mark.usefixtures("two_speakers")
async def test_enabled_speaker_asked_after_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask a speaker again once it's enabled, from Home Assistant's reload of the entry."""
    await set_up(hass, config_entry)
    kitchen = kitchen_device(device_registry, config_entry)
    await set_disabled(hass, device_registry, kitchen.id, disabled=True)
    await run_updates(hass, freezer, 15)
    asked(aioclient_mock)

    await set_disabled(hass, device_registry, kitchen.id, disabled=False)
    freezer.tick(timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert ALARMS in asked_by(asked(aioclient_mock), SPEAKER)
    assert state(hass, KITCHEN_ALARMS) not in {None, STATE_UNAVAILABLE}
    await run_updates(hass, freezer, 15)
    assert asked_by(asked(aioclient_mock), SPEAKER) == EVERYTHING


@pytest.mark.usefixtures("two_speakers")
async def test_disabled_speaker_removed_when_google_drops_it(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Remove a disabled speaker, as an enabled one, once two lists in a row lack it."""
    await set_up(hass, config_entry)
    bedroom = bedroom_device(device_registry, config_entry)
    assert bedroom is not None
    await set_disabled(hass, device_registry, bedroom.id, disabled=True)

    await fetch_list(hass, config_entry, clock, 1)
    assert bedroom_device(device_registry, config_entry) is not None
    google.return_value = [kitchen_speaker()]
    await fetch_list(hass, config_entry, clock, 2)
    assert bedroom_device(device_registry, config_entry) is not None
    await fetch_list(hass, config_entry, clock, 3)

    assert bedroom_device(device_registry, config_entry) is None
    assert BEDROOM_ID not in config_entry.runtime_data.devices
