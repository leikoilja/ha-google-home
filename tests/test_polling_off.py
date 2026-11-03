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

from custom_components.google_home.account import KNOWN_HOSTS_INTERVAL
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARMS,
    CONF_KNOWN_HOSTS,
    DOMAIN,
    FETCH_DEVICES_INTERVAL,
    FOUND_DEVICE_FETCH_DELAY,
    HEADER_CAST_LOCAL_AUTH,
    UPDATE_INTERVAL,
)
from custom_components.google_home.exceptions import DeviceRequestFailed

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components.repairs import RepairsFlowResult, repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.registry import SAVE_DELAY
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    DELETE,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    ForToken,
    Replies,
    kitchen_speaker,
)
from .test_coordinators import BEDROOM_ALARMS
from .test_diagnostics import TV, TV_CLOUD_ID, TV_NAME
from .test_missing_devices import ALARM_ID, found
from .test_sensor import error_message
from .test_setup import (
    ALARMS_SENSOR,
    DEVICE_SENSOR,
    STATES,
    requests,
    set_up,
    state,
    updated_at,
)
from .test_unsupported_devices import ALARMS, INFO, REBOOT, SPEAKER, SUPPORTED

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


async def test_known_host_asked_only_at_refresh_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Look for a speaker without an address at its known host only at a refresh.

    Its known host didn't answer at setup. Nothing asks it again 5 minutes later, when
    an update would with polling on; a refresh then does, and updates the speaker,
    without fetching Google's list.
    """
    google.return_value = [kitchen_speaker(None)]
    replies[SPEAKER][INFO] = TimeoutError()
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_KNOWN_HOSTS: [SPEAKER]}
    )
    await set_up_without_polling(hass, config_entry)
    replies[SPEAKER][INFO] = (
        HTTPStatus.OK,
        {"device_info": {"cloud_device_id": SPEAKER_CLOUD_ID}},
    )
    aioclient_mock.mock_calls.clear()

    clock.return_value = KNOWN_HOSTS_INTERVAL
    freezer.tick(timedelta(seconds=KNOWN_HOSTS_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert requests(aioclient_mock) == []

    # Its sensors are unavailable, which the integration's action refuses, and its
    # alarms sensor isn't added until it answers
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {ATTR_ENTITY_ID: DEVICE_SENSOR},
        blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state(hass, DEVICE_SENSOR) == SPEAKER
    assert state(hass, ALARMS_SENSOR) == STATES[ALARMS_SENSOR]
    assert google.call_count == 1


async def press_reboot(hass: HomeAssistant) -> None:
    """Press the speaker's reboot button."""
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.kitchen_speaker_reboot"},
        blocking=True,
    )


@pytest.mark.parametrize(
    ("polling", "advice", "logged"),
    [
        pytest.param(
            True,
            "The integration keeps asking Google for one, so try again later.",
            "Token will be refreshed, please try again later.",
            id="polling on",
        ),
        pytest.param(
            False,
            "Polling is turned off, so the integration doesn't ask Google again by "
            "itself: run the Refresh devices action, then try again.",
            "Polling is off: run Refresh devices, then try again.",
            id="polling off",
        ),
    ],
)
async def test_token_rejected_says_how_to_get_new_one(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    polling: bool,
    advice: str,
    logged: str,
) -> None:
    """Say how a speaker that rejects its token gets a new one, and get it that way.

    With polling on, the next update asks Google again by itself. With polling off,
    nothing does until a refresh, so the error says to run Refresh devices.
    """
    hass.config_entries.async_update_entry(
        config_entry, pref_disable_polling=not polling
    )
    await set_up(hass, config_entry)
    # The speaker's token changed, and Google doesn't have the new one yet
    replies[SPEAKER][REBOOT] = ForToken(NEW_TOKEN, (HTTPStatus.OK, {}))

    with pytest.raises(DeviceRequestFailed) as err:
        await press_reboot(hass)

    assert error_message(err.value) == (
        f"{SPEAKER_NAME} rejected its token, and getting a new one from Google "
        f"didn't help. {advice}"
    )
    assert (
        f"Failed to send the request to {SPEAKER_NAME} due to invalid token. {logged}"
    ) in [record.getMessage() for record in caplog.records]

    google.return_value = [
        found(
            SPEAKER_ID,
            SPEAKER,
            NEW_TOKEN,
            name=SPEAKER_NAME,
            cloud_device_id=SPEAKER_CLOUD_ID,
        )
    ]
    if polling:
        freezer.tick(timedelta(seconds=UPDATE_INTERVAL))
        async_fire_time_changed(hass)
    else:
        await refresh_devices(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    aioclient_mock.mock_calls.clear()

    await press_reboot(hass)

    assert [
        headers[HEADER_CAST_LOCAL_AUTH]
        for _, _, _, headers in aioclient_mock.mock_calls
    ] == [NEW_TOKEN]


# How a delete's error for one device ends: as before, or, when the device rejected
# its token while polling is off, with what to do instead
TRY_LATER = "Check that it's online and try again later."
RUN_REFRESH = (
    "It rejected its token, and getting a new one from Google didn't help. "
    "Polling is turned off, so the integration doesn't ask Google again by "
    "itself: run the Refresh devices action, then try again."
)
NOT_FETCHED = (
    f"Couldn't get the current alarms and timers from {SPEAKER_NAME}, so nothing "
    "was deleted from it."
)
NOT_DELETED = (
    f"{SPEAKER_NAME} didn't confirm deleting the alarms or timers, so they may "
    "still be set."
)


async def delete_all_alarms(
    hass: HomeAssistant, *entity_ids: str, skip_refresh: bool = False
) -> None:
    """Run the action that deletes all alarms of these alarms sensors."""
    await hass.services.async_call(
        DOMAIN,
        "delete_all_alarms",
        {ATTR_ENTITY_ID: list(entity_ids), "skip_refresh": skip_refresh},
        blocking=True,
    )


def alarm_ids(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return the IDs of the alarms that the alarms sensor shows."""
    alarms = hass.states.get(entity_id)
    assert alarms is not None
    return [alarm["alarm_id"] for alarm in alarms.attributes["alarms"]]


@pytest.mark.parametrize("polling", [True, False], ids=["polling on", "polling off"])
async def test_delete_fails_to_fetch_for_rejected_token(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    polling: bool,
) -> None:
    """Say how to get a new token when a delete can't fetch the alarms, then delete once Google has it.

    The speaker got no delete request, so the action doesn't refresh it, and doesn't
    ask Google again. With polling off, nothing else does until a refresh.
    """
    hass.config_entries.async_update_entry(
        config_entry, pref_disable_polling=not polling
    )
    await set_up(hass, config_entry)
    # The speaker's token changed, and Google doesn't have the new one yet
    replies[SPEAKER][ALARMS] = ForToken(NEW_TOKEN, SUPPORTED[ALARMS])
    replies[SPEAKER][DELETE] = ForToken(NEW_TOKEN, (HTTPStatus.OK, {"success": True}))
    fetched = google.call_count
    aioclient_mock.mock_calls.clear()

    with pytest.raises(HomeAssistantError) as err:
        await delete_all_alarms(hass, ALARMS_SENSOR)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        error_message(err.value)
        == f"{NOT_FETCHED} {TRY_LATER if polling else RUN_REFRESH}"
    )
    assert requests(aioclient_mock) == [("GET", API_ENDPOINT_ALARMS, None)]
    assert google.call_count == fetched

    google.return_value = [
        found(
            SPEAKER_ID,
            SPEAKER,
            NEW_TOKEN,
            name=SPEAKER_NAME,
            cloud_device_id=SPEAKER_CLOUD_ID,
        )
    ]
    if polling:
        freezer.tick(timedelta(seconds=UPDATE_INTERVAL))
        async_fire_time_changed(hass)
    else:
        await refresh_devices(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    aioclient_mock.mock_calls.clear()

    # Without it, the action updates the speaker again, whose fake answer still lists
    # the alarm
    await delete_all_alarms(hass, ALARMS_SENSOR, skip_refresh=True)

    assert [
        (method.upper(), headers[HEADER_CAST_LOCAL_AUTH])
        for method, _, _, headers in aioclient_mock.mock_calls
    ] == [("GET", NEW_TOKEN), ("POST", NEW_TOKEN)]
    assert alarm_ids(hass, ALARMS_SENSOR) == []


@pytest.mark.parametrize(
    ("polling", "skip_refresh", "fetches"),
    [
        pytest.param(True, False, 0, id="polling on"),
        pytest.param(False, True, 0, id="polling off, skip refresh"),
        # The refresh updates the account, as nothing else does while polling is off
        pytest.param(False, False, 1, id="polling off, refresh"),
    ],
)
async def test_delete_rejected_for_token(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    polling: bool,
    skip_refresh: bool,
    fetches: int,
) -> None:
    """Say how to get a new token when the speaker rejects only the delete, and keep its alarm.

    Google's list was fetched at setup, which is in the same round, so the rejection
    gets no new token. With polling off, the action's refresh fetches the list, but
    Google still has the token that the speaker rejects.
    """
    hass.config_entries.async_update_entry(
        config_entry, pref_disable_polling=not polling
    )
    await set_up(hass, config_entry)
    replies[SPEAKER][DELETE] = ForToken(NEW_TOKEN, (HTTPStatus.OK, {"success": True}))
    fetched = google.call_count
    aioclient_mock.mock_calls.clear()

    with pytest.raises(HomeAssistantError) as err:
        await delete_all_alarms(hass, ALARMS_SENSOR, skip_refresh=skip_refresh)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        error_message(err.value)
        == f"{NOT_DELETED} {TRY_LATER if polling else RUN_REFRESH}"
    )
    assert requests(aioclient_mock)[:2] == [
        ("GET", API_ENDPOINT_ALARMS, None),
        ("POST", API_ENDPOINT_ALARM_DELETE, {"ids": [ALARM_ID]}),
    ]
    assert google.call_count - fetched == fetches
    assert alarm_ids(hass, ALARMS_SENSOR) == [ALARM_ID]


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("endpoint", "first_sentence"),
    [(ALARMS, NOT_FETCHED), (DELETE, NOT_DELETED)],
    ids=["fetch", "delete"],
)
async def test_delete_fails_another_way_while_polling_off(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    endpoint: str,
    first_sentence: str,
) -> None:
    """Keep the advice to try again later when the speaker fails for another reason than its token."""
    await set_up_without_polling(hass, config_entry)
    replies[SPEAKER][DELETE] = (HTTPStatus.OK, {"success": True})
    replies[SPEAKER][endpoint] = HTTPStatus.INTERNAL_SERVER_ERROR

    with pytest.raises(HomeAssistantError) as err:
        await delete_all_alarms(hass, ALARMS_SENSOR, skip_refresh=True)

    assert error_message(err.value) == f"{first_sentence} {TRY_LATER}"


@pytest.mark.usefixtures("two_speakers")
@pytest.mark.parametrize("polling", [True, False], ids=["polling on", "polling off"])
@pytest.mark.parametrize(
    ("bedroom", "polling_on_error"),
    [
        pytest.param(
            {ALARMS: HTTPStatus.INTERNAL_SERVER_ERROR},
            "Couldn't get the current alarms and timers from these devices, so "
            "nothing was deleted from them: Bedroom speaker, Kitchen speaker. Check "
            "that they're online and try again later.",
            id="bedroom fetch fails",
        ),
        pytest.param(
            {DELETE: (HTTPStatus.OK, {"success": False})},
            "Couldn't delete alarms or timers from these devices, or confirm that "
            "they were deleted: Bedroom speaker, Kitchen speaker. Check that they're "
            "online and try again later.",
            id="bedroom delete unconfirmed",
        ),
    ],
)
async def test_delete_from_speakers_one_rejecting_token(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    polling: bool,
    bedroom: dict[str, HTTPStatus | tuple[HTTPStatus, object]],
    polling_on_error: str,
) -> None:
    """Say to refresh when one of the speakers that failed rejected its token while polling is off.

    The other speaker fails another way: its fetch, or its delete, which may have
    happened. The error is the same for both, so it doesn't say that nothing was
    deleted.
    """
    hass.config_entries.async_update_entry(
        config_entry, pref_disable_polling=not polling
    )
    await set_up(hass, config_entry)
    replies[SPEAKER][ALARMS] = ForToken(NEW_TOKEN, SUPPORTED[ALARMS])
    replies[BEDROOM].update(bedroom)

    with pytest.raises(HomeAssistantError) as err:
        await delete_all_alarms(hass, ALARMS_SENSOR, BEDROOM_ALARMS)

    assert error_message(err.value) == (
        polling_on_error
        if polling
        else "Couldn't delete alarms or timers from these devices, or confirm that "
        "they were deleted: Bedroom speaker, Kitchen speaker. At least one of them "
        "rejected its token, and getting a new one from Google didn't help. Polling "
        "is turned off, so the integration doesn't ask Google again by itself: run "
        "the Refresh devices action, check that the devices are online, then try "
        "again."
    )
