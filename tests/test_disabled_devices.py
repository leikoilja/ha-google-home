"""Tests for devices that the user disabled in Home Assistant, running inside Home Assistant.

As in test_coordinators, only glocaltokens, mDNS and the speakers' answers are faked.
A disabled device is asked nothing until it's enabled again, and Home Assistant then
reloads the entry. It stays in Google's list handling meanwhile.
"""

import asyncio
from datetime import timedelta
from unittest.mock import Mock, patch

from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import DOMAIN

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL, STATE_UNAVAILABLE
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
from .test_missing_devices import failure_logged, logged
from .test_polling_off import set_up_without_polling
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


@pytest.mark.usefixtures("two_speakers")
@pytest.mark.parametrize(
    ("disable_last", "unlisted"),
    [(True, False), (False, False), (False, True)],
    ids=["all-disabled", "enabled-listed", "enabled-unlisted"],
)
async def test_fetch_failure_without_polling_with_disabled_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    disable_last: bool,
    unlisted: bool,
) -> None:
    """Say to reload only when no enabled device can request another account fetch.

    A refresh starts a fetch, then the last enabled speaker may be disabled before
    Google fails. If it stays enabled, even if recently unlisted, its entities can
    still refresh the account once the wait has passed. Otherwise only a reload
    fetches again: neither the clock nor Refresh devices does.
    """
    await set_up_without_polling(hass, config_entry)
    kitchen = kitchen_device(device_registry, config_entry)
    await set_disabled(hass, device_registry, kitchen.id, disabled=True)
    if unlisted:
        google.return_value = [kitchen_speaker()]
        await fetch_list(hass, config_entry, clock, 1)
        assert config_entry.runtime_data.devices[BEDROOM_ID].data is None

    started, release = asyncio.Event(), asyncio.Event()
    error = ClientConnectionError("Google is unreachable")

    async def fail_fetch(**_options: object) -> None:
        started.set()
        await release.wait()
        raise error

    # A refresh can fetch again once the scheduled interval has passed.
    clock.return_value = config_entry.runtime_data.client.next_scheduled_fetch
    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.async_get_google_devices_and_home_graph",
        side_effect=fail_fetch,
    ):
        refresh = asyncio.create_task(
            hass.services.async_call(
                DOMAIN,
                "refresh_devices",
                {ATTR_ENTITY_ID: BEDROOM_ALARMS},
                blocking=True,
            )
        )
        await started.wait()
        if disable_last:
            bedroom = bedroom_device(device_registry, config_entry)
            assert bedroom is not None
            # Do not wait for Home Assistant's tasks until the held fetch ends.
            device_registry.async_update_device(
                bedroom.id, disabled_by=dr.DeviceEntryDisabler.USER
            )
        release.set()
        await refresh
        await hass.async_block_till_done(wait_background_tasks=True)

    if disable_last:
        later = "polling is off, so reload the integration to fetch it"
        expected = ("ERROR", f"Failed to fetch Google's device list ({later}): {error}")
    else:
        expected = failure_logged(error, 20)
    assert expected in logged(caplog)
    errors = [line for level, line in logged(caplog) if level == "ERROR"]
    assert errors == [expected[1]]

    fetched = google.call_count
    # Keep both clocks together: a pending debounced refresh runs after a few
    # seconds, before the fetch is due, rather than 20 minutes later.
    for _ in range(20 * 60 // 15):
        clock.return_value += 15
        await run_updates(hass, freezer, 15)
    assert google.call_count == fetched
    await hass.services.async_call(
        DOMAIN,
        "refresh_devices",
        {ATTR_ENTITY_ID: ENTITY_MATCH_ALL},
        blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert google.call_count == fetched + (0 if disable_last else 1)

    if disable_last:
        assert await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()
        assert google.call_count == fetched + 1
