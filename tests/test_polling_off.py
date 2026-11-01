"""Tests for the integration while polling is turned off in its system options.

Home Assistant then schedules no updates, and the integration schedules no fetches of
Google's list. A repair says so, and can turn polling back on or be hidden. Refreshes
that are asked for still update the account, so Google's list is fetched when due and
tokens renew.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import partial
from http import HTTPStatus
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import WebSocketGenerator

from custom_components.google_home.const import (
    API_ENDPOINT_ALARMS,
    DOMAIN,
    FETCH_DEVICES_INTERVAL,
    FOUND_DEVICE_FETCH_DELAY,
    HEADER_CAST_LOCAL_AUTH,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components.repairs import RepairsFlowResult, repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.registry import SAVE_DELAY
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    ForToken,
    Replies,
)
from .test_coordinators import BEDROOM_ALARMS
from .test_diagnostics import TV, TV_CLOUD_ID, TV_NAME
from .test_missing_devices import found
from .test_setup import ALARMS_SENSOR, STATES, requests, set_up, state, updated_at
from .test_unsupported_devices import ALARMS, SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order

ISSUE_ID = "polling_disabled"
NEW_TOKEN = "new-token"
# An alarm that the speaker has once it accepts its new token: 1800000000 s is
# 2027-01-15 08:00 UTC, shown in the tests' time zone US/Pacific
NEW_ALARM = {"id": "alarm/new", "fire_time": 1800000000000, "status": 1}
NEW_ALARM_STATE = "2027-01-15T00:00:00-08:00"


async def set_up_without_polling(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry with polling turned off, as its system options save it."""
    hass.config_entries.async_update_entry(entry, pref_disable_polling=True)
    await set_up(hass, entry)


async def set_polling_in_system_options(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    *,
    enabled: bool,
) -> None:
    """Turn polling on or off as the frontend's system options do, which reloads."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "config_entries/update",
            "entry_id": entry.entry_id,
            "pref_disable_polling": not enabled,
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()


async def turn_on_in_system_options(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Turn polling on in the system options."""
    await set_polling_in_system_options(hass, entry, hass_ws_client, enabled=True)


async def choose_in_repair(
    hass: HomeAssistant, entry: MockConfigEntry, choice: str
) -> RepairsFlowResult:
    """Open the repair's fix, which changes nothing until the user makes the choice."""
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_init(DOMAIN, context={"issue_id": ISSUE_ID})
    assert (result["type"], result.get("menu_options")) == (
        FlowResultType.MENU,
        ["turn_on", "keep_off"],
    )
    assert entry.pref_disable_polling

    return await manager.async_configure(result["flow_id"], {"next_step_id": choice})


async def turn_on_with_repair(
    hass: HomeAssistant, entry: MockConfigEntry, _: WebSocketGenerator
) -> None:
    """Choose to turn polling back on in the repair's fix."""
    result = await choose_in_repair(hass, entry, "turn_on")

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def refresh_devices(hass: HomeAssistant) -> None:
    """Run the integration's action to refresh the devices."""
    await hass.services.async_call(
        DOMAIN, "refresh_devices", {ATTR_ENTITY_ID: ALARMS_SENSOR}, blocking=True
    )


async def update_entity(hass: HomeAssistant) -> None:
    """Run Home Assistant's action to update an entity."""
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant", "update_entity", {ATTR_ENTITY_ID: ALARMS_SENSOR}, blocking=True
    )


@pytest.mark.usefixtures("replies")
@pytest.mark.parametrize(
    ("error", "entry_state"),
    [(None, ConfigEntryState.LOADED), (RuntimeError(), ConfigEntryState.SETUP_RETRY)],
    ids=["loaded", "setup retry"],
)
async def test_repair_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
    error: Exception | None,
    entry_state: ConfigEntryState,
) -> None:
    """Show a warning for the entry, whose fix says what polling being off means.

    Also while setup is retried, as polling stays off meanwhile. Home Assistant opens
    the fix straight away, so the fix's text links to the docs.
    """
    google.side_effect = error
    hass.config_entries.async_update_entry(config_entry, pref_disable_polling=True)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is entry_state
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None
    assert (
        issue.is_fixable,
        issue.severity,
        issue.config_entry_id,
        issue.translation_key,
    ) == (True, ir.IssueSeverity.WARNING, config_entry.entry_id, ISSUE_ID)
    # The Repairs list shows its title; the fix's texts are checked as it runs
    text = await async_get_translations(hass, "en", "issues", [DOMAIN])
    assert f"component.{DOMAIN}.issues.{ISSUE_ID}.title" in text
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_init(DOMAIN, context={"issue_id": ISSUE_ID})
    assert result.get("description_placeholders") == {
        "docs_url": "https://ha-google-home.pages.dev/configuration/#turn-off-polling"
    }


@pytest.mark.usefixtures("google", "replies")
async def test_no_repair_while_polling_on(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Show no repair with polling on, the default."""
    await set_up(hass, config_entry)

    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID) is None


@pytest.mark.usefixtures("replies")
async def test_nothing_scheduled_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Neither update the speaker nor fetch Google's list without being asked.

    Not even for a Cast device that mDNS finds and Google's list doesn't have, such
    as a TV, which gets a fetch soon with polling on.
    """
    await set_up_without_polling(hass, config_entry)
    config_entry.runtime_data.client.found_devices.async_device_found(
        TV_CLOUD_ID, TV_NAME, TV
    )

    # Past the fetch for the TV
    clock.return_value = FOUND_DEVICE_FETCH_DELAY + 1
    assert await updated_at(hass, aioclient_mock, freezer) == []
    # Past the scheduled fetch
    clock.return_value = FETCH_DEVICES_INTERVAL + 1
    freezer.tick(timedelta(seconds=FETCH_DEVICES_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert requests(aioclient_mock) == []
    assert google.call_count == 1


@pytest.mark.usefixtures("replies")
@pytest.mark.parametrize("turn_on", [turn_on_in_system_options, turn_on_with_repair])
async def test_turn_polling_back_on(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    issue_registry: ir.IssueRegistry,
    google: Mock,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    turn_on: Callable[
        [HomeAssistant, MockConfigEntry, WebSocketGenerator], Awaitable[None]
    ],
) -> None:
    """Remove the repair and update on schedule again, after loading the entry again."""
    await set_up_without_polling(hass, config_entry)

    await turn_on(hass, config_entry, hass_ws_client)
    await hass.async_block_till_done()

    assert not config_entry.pref_disable_polling
    assert config_entry.state is ConfigEntryState.LOADED
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID) is None
    # Loading it again fetched Google's list
    assert google.call_count == 2
    assert await updated_at(hass, aioclient_mock, freezer) == list(range(15, 181, 15))


@pytest.mark.usefixtures("google", "replies")
async def test_keep_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Hide the repair, also after a restart, until polling is turned on and off again.

    Polling stays off, and the entry isn't loaded again.
    """
    await set_up_without_polling(hass, config_entry)

    result = await choose_in_repair(hass, config_entry, "keep_off")

    assert (result["type"], result.get("reason")) == (
        FlowResultType.ABORT,
        "polling_kept_off",
    )
    assert config_entry.pref_disable_polling
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None and issue.dismissed_version is not None

    # The registry's part of a restart: Home Assistant saves it, and loads it again
    # before setup
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    freezer.tick(timedelta(seconds=SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await issue_registry.async_load()
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None and not issue.active
    await set_up(hass, config_entry)

    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None and issue.active and issue.dismissed_version is not None

    await set_polling_in_system_options(
        hass, config_entry, hass_ws_client, enabled=True
    )
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID) is None
    await set_polling_in_system_options(
        hass, config_entry, hass_ws_client, enabled=False
    )

    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None and issue.dismissed_version is None


@pytest.mark.usefixtures("google", "replies")
async def test_keep_polling_off_once_turned_on(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Finish the fix without saying polling stays off, if it was turned on meanwhile."""
    await set_up_without_polling(hass, config_entry)
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_init(DOMAIN, context={"issue_id": ISSUE_ID})
    await set_polling_in_system_options(
        hass, config_entry, hass_ws_client, enabled=True
    )

    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "keep_off"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not config_entry.pref_disable_polling
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_ID) is None


@pytest.mark.parametrize(
    ("refresh", "speakers"),
    [
        (refresh_devices, {SPEAKER: ALARMS_SENSOR}),
        (update_entity, {SPEAKER: ALARMS_SENSOR}),
        (refresh_devices, {SPEAKER: ALARMS_SENSOR, BEDROOM: BEDROOM_ALARMS}),
    ],
    ids=["refresh_devices", "update_entity", "refresh_devices two speakers"],
)
async def test_refresh_renews_token_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    refresh: Callable[[HomeAssistant], Awaitable[None]],
    speakers: dict[str, str],
) -> None:
    """Get the speakers' new tokens from Google at a refresh, and show what they then answer.

    Only the refresh updates the account, so without it the tokens setup got stay.
    With two speakers, both are updated at once and share one fetch.
    """
    devices = {
        SPEAKER: partial(
            found,
            SPEAKER_ID,
            SPEAKER,
            name=SPEAKER_NAME,
            cloud_device_id=SPEAKER_CLOUD_ID,
        ),
        BEDROOM: partial(found, BEDROOM_ID, BEDROOM, name="Bedroom speaker"),
    }
    google.return_value = [devices[address]() for address in speakers]
    replies[BEDROOM] = dict(SUPPORTED)
    await set_up_without_polling(hass, config_entry)
    # The speakers' tokens changed: they accept only the new ones, which Google's list
    # has now
    for address in speakers:
        replies[address][ALARMS] = ForToken(
            NEW_TOKEN, (HTTPStatus.OK, {"alarm": [NEW_ALARM], "timer": []})
        )
    google.return_value = [devices[address](token=NEW_TOKEN) for address in speakers]
    aioclient_mock.mock_calls.clear()

    await refresh(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert google.call_count == 2
    assert {address: state(hass, sensor) for address, sensor in speakers.items()} == (
        dict.fromkeys(speakers, NEW_ALARM_STATE)
    )
    last_tokens = {
        str(url.host): headers[HEADER_CAST_LOCAL_AUTH]
        for _, url, _, headers in aioclient_mock.mock_calls
        if url.path_qs.removeprefix("/") == API_ENDPOINT_ALARMS
    }
    assert last_tokens == dict.fromkeys(speakers, NEW_TOKEN)


@pytest.mark.usefixtures("replies")
async def test_refresh_fetches_list_only_when_due_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Fetch Google's list at a refresh once 20 minutes have passed since setup's.

    Not before, as mDNS found no device that the list doesn't have.
    """
    await set_up_without_polling(hass, config_entry)

    await refresh_devices(hass)
    assert google.call_count == 1

    # Past the cooldown of Home Assistant's requested refreshes, and the fetch interval
    clock.return_value = FETCH_DEVICES_INTERVAL
    freezer.tick(timedelta(seconds=FETCH_DEVICES_INTERVAL))
    async_fire_time_changed(hass)
    await refresh_devices(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert google.call_count == 2
    assert state(hass, ALARMS_SENSOR) == STATES[ALARMS_SENSOR]


@pytest.mark.usefixtures("replies")
async def test_refresh_fetches_list_for_found_device_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Fetch Google's list at the first refresh 30 seconds after mDNS finds a new device.

    It may have just been added in the Google Home app. Without polling, nothing
    fetches for it before that refresh.
    """
    await set_up_without_polling(hass, config_entry)
    config_entry.runtime_data.client.found_devices.async_device_found(
        TV_CLOUD_ID, TV_NAME, TV
    )

    await refresh_devices(hass)
    assert google.call_count == 1

    # Past the cooldown of Home Assistant's requested refreshes, and the delay
    clock.return_value = FOUND_DEVICE_FETCH_DELAY
    freezer.tick(timedelta(seconds=FOUND_DEVICE_FETCH_DELAY))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert google.call_count == 1
    await refresh_devices(hass)

    assert google.call_count == 2
