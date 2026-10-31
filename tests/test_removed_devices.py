"""Tests for removing the devices that Google no longer lists, running inside Home Assistant.

As in test_coordinators, only glocaltokens, mDNS and the speakers' answers are faked,
and the account's update and the speakers' updates run in the order a test needs.
"""

from datetime import timedelta
from http import HTTPStatus
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import DOMAIN, FETCH_DEVICES_INTERVAL

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    SPEAKER_ID,
    Replies,
    bedroom_speaker,
    kitchen_speaker,
)
from .test_coordinators import (
    BEDROOM_ALARMS,
    EVERYTHING,
    KITCHEN_ALARMS,
    REJECTING,
    asked,
    asked_by,
    runtime,
    update_account,
)
from .test_missing_devices import FETCH_ERRORS, UNREACHABLE, answered, found, logged
from .test_setup import set_up, state
from .test_unsupported_devices import SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order

REMOVED_BEDROOM = ("INFO", "Removed Bedroom speaker, which Google no longer lists")


def entity_ids(entity_registry: er.EntityRegistry, entry: MockConfigEntry) -> set[str]:
    """Return the IDs of the entry's entities."""
    return {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }


def bedroom_device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry
) -> dr.DeviceEntry | None:
    """Return the entry's device of the bedroom speaker, if it has one."""
    return device_registry.async_get_device_by_identifier(
        (DOMAIN, BEDROOM_ID), entry.entry_id
    )


async def fetch_list(
    hass: HomeAssistant, entry: MockConfigEntry, clock: Mock, fetches: int
) -> None:
    """Run the account's update with the scheduled fetch that many intervals after setup's."""
    clock.return_value = fetches * FETCH_DEVICES_INTERVAL
    await update_account(hass, entry)


@pytest.mark.usefixtures("two_speakers")
async def test_speaker_removed_after_two_lists_without_it(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Remove a speaker, with its entities, once two fetches in a row of Google's list lack it.

    Updates that don't fetch the list don't count, and the other speaker stays.
    """
    await set_up(hass, config_entry)
    kitchen_entities = {
        entity_id
        for entity_id in entity_ids(entity_registry, config_entry)
        if "kitchen_speaker" in entity_id
    }
    google.return_value = [kitchen_speaker()]

    await fetch_list(hass, config_entry, clock, 1)
    await update_account(hass, config_entry)
    await update_account(hass, config_entry)

    assert bedroom_device(device_registry, config_entry) is not None
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE
    assert REMOVED_BEDROOM not in logged(caplog)

    await fetch_list(hass, config_entry, clock, 2)

    assert bedroom_device(device_registry, config_entry) is None
    assert entity_ids(entity_registry, config_entry) == kitchen_entities
    assert hass.states.get(BEDROOM_ALARMS) is None
    assert list(runtime(config_entry).devices) == [SPEAKER_ID]
    assert state(hass, KITCHEN_ALARMS) != STATE_UNAVAILABLE
    assert logged(caplog).count(REMOVED_BEDROOM) == 1


@pytest.mark.usefixtures("two_speakers")
@pytest.mark.parametrize("error", [*FETCH_ERRORS, UNREACHABLE])
async def test_failed_fetches_dont_count_toward_removal(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
    error: Exception,
) -> None:
    """Keep a speaker that one list lacked while the next fetches fail, and remove it after the next list without it."""
    await set_up(hass, config_entry)
    google.return_value = [kitchen_speaker()]
    await fetch_list(hass, config_entry, clock, 1)

    google.side_effect = error
    await fetch_list(hass, config_entry, clock, 2)
    await fetch_list(hass, config_entry, clock, 3)

    assert google.call_count == 4
    assert bedroom_device(device_registry, config_entry) is not None

    google.side_effect = None
    await fetch_list(hass, config_entry, clock, 4)

    assert bedroom_device(device_registry, config_entry) is None


@pytest.mark.usefixtures("two_speakers")
async def test_lists_that_speakers_fetch_count_toward_removal(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Count each list Google answers, also one that a speaker's rejected token fetches.

    Such a fetch, and the account's fetch of the then unknown list, can both end
    between two of the account's checks for devices to remove. A list that has the speaker again starts
    the count over. Once two lists in a row lack it, it's removed when the list is
    known again.
    """
    await set_up(hass, config_entry)
    data = runtime(config_entry)
    google.return_value = [kitchen_speaker()]
    await fetch_list(hass, config_entry, clock, 1)
    # An update with no fetch due, so the kitchen speaker's token can fetch the list
    await update_account(hass, config_entry)

    # The kitchen speaker rejects the token in the list that its update fetches,
    # which has the bedroom speaker again, so the list is unknown
    replies[SPEAKER] = dict(REJECTING)
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    await data.devices[SPEAKER_ID].async_refresh()
    assert google.call_count == 3
    assert not data.client.google_devices_fetched
    # The account fetches the unknown list, which lacks the bedroom speaker
    replies[SPEAKER] = dict(SUPPORTED)
    google.return_value = [kitchen_speaker()]
    await update_account(hass, config_entry)
    assert google.call_count == 4

    assert bedroom_device(device_registry, config_entry) is not None

    # The kitchen speaker's rejected token fetches another list without it, so two
    # lists in a row lack it, but the list is unknown until the account's next
    # fetch, which fails
    await update_account(hass, config_entry)
    replies[SPEAKER] = dict(REJECTING)
    await data.devices[SPEAKER_ID].async_refresh()
    assert google.call_count == 5
    google.side_effect = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    await update_account(hass, config_entry)
    assert google.call_count == 6

    assert bedroom_device(device_registry, config_entry) is not None

    google.side_effect = None
    replies[SPEAKER] = dict(SUPPORTED)
    await fetch_list(hass, config_entry, clock, 2)

    assert google.call_count == 7
    assert bedroom_device(device_registry, config_entry) is None


@pytest.mark.usefixtures("two_speakers")
async def test_speaker_listed_again_between_lists_without_it_stays(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Keep a speaker that a list has again before a second list in a row lacks it."""
    await set_up(hass, config_entry)
    entities = entity_ids(entity_registry, config_entry)
    bedroom = bedroom_device(device_registry, config_entry)
    assert bedroom is not None

    for fetch, listed in enumerate(
        ([kitchen_speaker()], [kitchen_speaker(), bedroom_speaker()]), start=1
    ):
        google.return_value = listed
        await fetch_list(hass, config_entry, clock, fetch)
    google.return_value = [kitchen_speaker()]
    await fetch_list(hass, config_entry, clock, 3)

    assert bedroom_device(device_registry, config_entry) == bedroom
    assert entity_ids(entity_registry, config_entry) == entities


@pytest.mark.usefixtures("two_speakers")
@pytest.mark.parametrize("device_id", [BEDROOM_ID, "bedroom-set-up-again"])
async def test_removed_speaker_listed_again_gets_its_entity_ids(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    entity_registry: er.EntityRegistry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    device_id: str,
) -> None:
    """Add a removed speaker's entities again when Google lists it again, with their old IDs.

    With the same ID, as if Google had only missed it, or with a new ID and the same
    name, as after a factory reset. Only the new coordinator asks the speaker: the
    removed one doesn't run again.
    """
    await set_up(hass, config_entry)
    entities = entity_ids(entity_registry, config_entry)
    google.return_value = [kitchen_speaker()]
    await fetch_list(hass, config_entry, clock, 1)
    await fetch_list(hass, config_entry, clock, 2)
    assert BEDROOM_ALARMS not in entity_ids(entity_registry, config_entry)

    google.return_value = [
        kitchen_speaker(),
        found(device_id, BEDROOM, name="Bedroom speaker"),
    ]
    await fetch_list(hass, config_entry, clock, 3)

    assert entity_ids(entity_registry, config_entry) == entities
    assert state(hass, BEDROOM_ALARMS) == "2023-11-14T14:13:20-08:00"

    asked(aioclient_mock)
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert asked_by(asked(aioclient_mock), BEDROOM) == EVERYTHING


@pytest.mark.usefixtures("google", "replies")
async def test_device_no_list_has_is_removed_after_two_lists(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Remove a device of the entry that Google dropped before the integration loaded, after setup's list and one more.

    A device of another config entry stays, even with this integration's identifier.
    """
    old = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "old")},
        name="Old speaker",
    )
    other_entry = MockConfigEntry(domain="test")
    other_entry.add_to_hass(hass)
    other = device_registry.async_get_or_create(
        config_entry_id=other_entry.entry_id, identifiers={(DOMAIN, "other")}
    )

    await set_up(hass, config_entry)
    assert device_registry.async_get(old.id) is not None

    await fetch_list(hass, config_entry, clock, 1)

    assert device_registry.async_get(old.id) is None
    assert device_registry.async_get(other.id) is not None
    assert ("INFO", "Removed Old speaker, which Google no longer lists") in logged(
        caplog
    )
