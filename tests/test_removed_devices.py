"""Tests for removing the devices that Google no longer lists, running inside Home Assistant.

As in test_coordinators, only glocaltokens, mDNS and the speakers' answers are faked,
and the account's update and the speakers' updates run in the order a test needs.
"""

from collections.abc import Iterator
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

from freezegun.api import FrozenDateTimeFactory
from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module
from glocaltokens.scanner import NetworkDevice
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import DOMAIN, FETCH_DEVICES_INTERVAL

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    Replies,
    bedroom_speaker,
    kitchen_speaker,
)
from .test_coordinators import (
    BEDROOM_ALARMS,
    BEDROOM_DND,
    EVERYTHING,
    KITCHEN_ALARMS,
    REJECTING,
    asked,
    asked_by,
    runtime,
    update_account,
)
from .test_missing_devices import (
    FETCH_ERRORS,
    LOCAL_AUTH_TOKEN,
    UNREACHABLE,
    answered,
    found,
    logged,
)
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


@pytest.mark.usefixtures("two_speakers")
async def test_speaker_listed_again_gets_its_settings_back(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Give a removed speaker that Google lists again under the same ID back what the user changed.

    As if Google's list had missed it twice: Home Assistant keeps the settings of the
    entry's deleted device and entities, and restores them when they come back.
    """
    await set_up(hass, config_entry)
    bedroom = bedroom_device(device_registry, config_entry)
    assert bedroom is not None
    upstairs = area_registry.async_create("Upstairs")
    device_registry.async_update_device(
        bedroom.id, area_id=upstairs.id, name_by_user="Guest room speaker"
    )
    entity_registry.async_update_entity(
        BEDROOM_ALARMS, new_entity_id="sensor.guest_alarms", name="Guest alarms"
    )
    entity_registry.async_update_entity(
        BEDROOM_DND, disabled_by=er.RegistryEntryDisabler.USER
    )
    google.return_value = [kitchen_speaker()]
    await fetch_list(hass, config_entry, clock, 1)
    await fetch_list(hass, config_entry, clock, 2)
    assert bedroom_device(device_registry, config_entry) is None

    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    await fetch_list(hass, config_entry, clock, 3)

    restored = bedroom_device(device_registry, config_entry)
    assert restored is not None
    assert (restored.id, restored.area_id, restored.name_by_user) == (
        bedroom.id,
        upstairs.id,
        "Guest room speaker",
    )
    alarms = entity_registry.async_get("sensor.guest_alarms")
    assert alarms is not None
    assert (alarms.unique_id, alarms.name) == (f"{BEDROOM_ID}/alarms", "Guest alarms")
    assert state(hass, "sensor.guest_alarms") == "2023-11-14T14:13:20-08:00"
    dnd = entity_registry.async_get(BEDROOM_DND)
    assert dnd is not None
    assert dnd.disabled_by is er.RegistryEntryDisabler.USER
    assert hass.states.get(BEDROOM_DND) is None


def in_home_graph(
    device_id: str,
    cloud_device_id: str,
    name: str,
    token: str = LOCAL_AUTH_TOKEN,
) -> HomeGraph.Device:
    """Return a speaker as Google's home graph has it."""
    return HomeGraph.Device(
        id=HomeGraph.DeviceId(
            device_id=device_id,
            agent_info=HomeGraph.DeviceId.AgentInfo(unique_id=cloud_device_id),
        ),
        display_name=name,
        local_auth_token=token,
        hardware=HomeGraph.Device.Hardware(model="Nest Audio"),
    )


def home_graph_with(*devices: HomeGraph.Device) -> HomeGraph:
    """Return a home graph with one home that has these devices."""
    return HomeGraph(homes=[HomeGraph.Home(devices=devices)])


KITCHEN_IN_HOME_GRAPH = in_home_graph(SPEAKER_ID, SPEAKER_CLOUD_ID, SPEAKER_NAME)


@pytest.fixture(name="home_graph")
def fixture_home_graph(
    mock_async_zeroconf: MagicMock,  # pylint: disable=unused-argument
    replies: Replies,
) -> Iterator[Mock]:
    """Fake Google's home graph, with the kitchen and the bedroom speaker, and mDNS, which finds both.

    Unlike with the google fixture, glocaltokens itself makes the device list from
    the home graph, and leaves out the devices that it can't use.
    """
    replies[BEDROOM] = dict(SUPPORTED)
    with (
        patch(
            "glocaltokens.client.GLocalAuthenticationTokens.get_home_graph",
            autospec=True,
            return_value=home_graph_with(
                KITCHEN_IN_HOME_GRAPH,
                in_home_graph(BEDROOM_ID, BEDROOM_ID, "Bedroom speaker"),
            ),
        ) as home_graph,
        patch(
            "glocaltokens.client.discover_devices",
            return_value=[
                NetworkDevice(
                    SPEAKER_NAME, SPEAKER, 8009, "Nest Audio", SPEAKER_CLOUD_ID
                ),
                NetworkDevice(
                    "Bedroom speaker", BEDROOM, 8009, "Nest Audio", BEDROOM_ID
                ),
            ],
        ),
        patch("custom_components.google_home.mdns.AsyncServiceBrowser"),
    ):
        yield home_graph


@pytest.mark.parametrize(
    "unusable",
    [
        pytest.param({"token": ""}, id="no-local-token"),
        pytest.param({"token": "x" * 20}, id="token-of-another-format"),
        pytest.param({"name": ""}, id="no-name"),
    ],
)
async def test_speaker_glocaltokens_leaves_out_stays(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
    unusable: dict[str, str],
) -> None:
    """Keep a speaker that Google's home graph still has while glocaltokens leaves it out of the list.

    glocaltokens skips a device without a local token, with a token of another
    format or without a name. Once the home graph lacks the speaker twice in a row,
    it's removed.
    """
    await set_up(hass, config_entry)
    assert state(hass, BEDROOM_ALARMS) == "2023-11-14T14:13:20-08:00"

    bedroom = {"name": "Bedroom speaker"} | unusable
    home_graph.return_value = home_graph_with(
        KITCHEN_IN_HOME_GRAPH, in_home_graph(BEDROOM_ID, BEDROOM_ID, **bedroom)
    )
    for fetch in (1, 2, 3):
        await fetch_list(hass, config_entry, clock, fetch)

    # Left out of the list, but not removed
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE
    assert bedroom_device(device_registry, config_entry) is not None

    home_graph.return_value = home_graph_with(KITCHEN_IN_HOME_GRAPH)
    await fetch_list(hass, config_entry, clock, 4)
    assert bedroom_device(device_registry, config_entry) is not None
    await fetch_list(hass, config_entry, clock, 5)

    assert bedroom_device(device_registry, config_entry) is None
