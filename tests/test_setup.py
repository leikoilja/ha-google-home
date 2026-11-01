"""Tests for the integration running inside Home Assistant.

Home Assistant sets up the entry, runs its updates and calls its actions. Only
glocaltokens, mDNS and the speaker's answers are faked, by the fixtures in conftest.py.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from http import HTTPStatus
from importlib import import_module
from pathlib import Path
from typing import TypedDict
from unittest.mock import Mock, patch

from freezegun.api import FrozenDateTimeFactory
import probatio
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    snapshot_platform,
)
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DO_NOT_DISTURB,
    CONF_KNOWN_HOSTS,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_ICON,
    ENTITY_MATCH_ALL,
    SERVICE_TURN_OFF,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.icon import async_get_icons
from homeassistant.setup import async_setup_component

from .conftest import (
    DELETE,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    Replies,
    kitchen_speaker,
)
from .test_missing_devices import ALARM_ID, TIMER_ID, rejected
from .test_unsupported_devices import DND, INFO, SPEAKER, VOLUME

# pylint: enable=wrong-import-order

DEVICE_SENSOR = "sensor.kitchen_speaker_device"
ALARMS_SENSOR = "sensor.kitchen_speaker_alarms"
DND_SWITCH = "switch.kitchen_speaker_do_not_disturb"
VOLUME_NUMBER = "number.kitchen_speaker_alarm_volume"
# The speaker's entities and their states, as it answers in SUPPORTED: an alarm at
# 1700000000 s, 22:13:20 UTC, shown in the tests' time zone US/Pacific, no timer,
# which the timers sensor shows as unavailable, alarm volume 0.7, and notifications
# not enabled, which is Do Not Disturb on
STATES = {
    DEVICE_SENSOR: SPEAKER,
    ALARMS_SENSOR: "2023-11-14T14:13:20-08:00",
    "sensor.kitchen_speaker_timers": STATE_UNAVAILABLE,
    DND_SWITCH: STATE_ON,
    VOLUME_NUMBER: "70",
    "button.kitchen_speaker_reboot": STATE_UNKNOWN,
}
# The icon that each entity has shown since before icons.json, in the states above.
# The reboot button has none of its own: the frontend shows its icon for restart.
ICONS = {
    DEVICE_SENSOR: "mdi:form-textbox-password",
    ALARMS_SENSOR: "mdi:alarm-multiple",
    "sensor.kitchen_speaker_timers": "mdi:timer-sand",
    DND_SWITCH: "mdi:minus-circle",
    VOLUME_NUMBER: "mdi:volume-high",
    "button.kitchen_speaker_reboot": None,
}
# The actions, each with data that it accepts
ACTIONS: dict[str, dict[str, object]] = {
    "reboot_device": {},
    "delete_alarm": {"alarm_id": ALARM_ID},
    "delete_timer": {"timer_id": TIMER_ID},
    "delete_all_alarms": {},
    "delete_all_timers": {},
    "refresh_devices": {},
}
# Home Assistant's own errors for an action whose entry isn't loaded, which it
# translates: "Config entry {entry_title} for integration {domain} is not loaded"
# and "Could not find config entry for integration {domain}"
NOT_LOADED = (
    "homeassistant",
    "service_config_entry_not_loaded",
    {"domain": DOMAIN, "entry_title": "test@example.com"},
)
NO_ENTRY = (
    "homeassistant",
    "service_found_no_config_entry_for_domain",
    {"domain": DOMAIN},
)


async def set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry as Home Assistant does at startup, and wait for it to finish."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def requests(aioclient_mock: AiohttpClientMocker) -> list[tuple[str, str, object]]:
    """Return the method, endpoint and JSON body of each request sent so far, in order."""
    return [
        (method.upper(), url.path_qs.removeprefix("/"), body)
        for method, url, body, _ in aioclient_mock.mock_calls
    ]


async def updated_at(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> list[int]:
    """Return when the speaker is updated in the next 3 minutes, checking every 15 seconds."""
    times: list[int] = []
    for seconds in range(15, 181, 15):
        aioclient_mock.mock_calls.clear()
        freezer.tick(timedelta(seconds=15))
        async_fire_time_changed(hass)
        # The update runs in the background, and sets the time of the next one
        await hass.async_block_till_done(wait_background_tasks=True)
        if ("GET", API_ENDPOINT_ALARMS, None) in requests(aioclient_mock):
            times.append(seconds)
    return times


async def reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry, then reload it, which unloads it and sets it up again."""
    await set_up(hass, entry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def refusals(
    hass: HomeAssistant, action: str, targets: dict[str, dict[str, str]]
) -> dict[str, tuple[str | None, str | None, dict[str, str] | None]]:
    """Call the action with data it accepts on each target, and return why each call failed."""
    errors = {}
    for name, target in targets.items():
        with pytest.raises(ServiceValidationError) as error:
            await hass.services.async_call(
                DOMAIN, action, {**target, **ACTIONS[action]}, blocking=True
            )
        errors[name] = (
            error.value.translation_domain,
            error.value.translation_key,
            error.value.translation_placeholders,
        )
    return errors


def state(hass: HomeAssistant, entity_id: str) -> str:
    """Return the entity's state."""
    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    return entity_state.state


class EntityIcons(TypedDict, total=False):
    """An entity's icons in icons.json."""

    default: str
    state: dict[str, str]
    range: dict[str, str]


async def shown_icons(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> dict[str, str | None]:
    """Return the icon that Home Assistant's frontend shows for each entity in STATES.

    An icon in the entity's state comes first. Otherwise the frontend looks up the
    icons that Home Assistant loaded, by platform and translation key, and picks as its
    getIconFromTranslations does: the icon for the state, else for a number the icon
    of the highest range at or below it, else the default. None means it has none
    there, so the frontend shows its own icon for the domain or device class.
    """
    loaded: dict[str, dict[str, EntityIcons]] = (
        await async_get_icons(hass, "entity", [DOMAIN])
    ).get(DOMAIN, {})
    shown: dict[str, str | None] = {}
    for entity_id in STATES:
        entry = entity_registry.async_get(entity_id)
        entity_state = hass.states.get(entity_id)
        assert entry is not None and entry.translation_key is not None
        assert entity_state is not None
        icons = loaded.get(entry.domain, {}).get(entry.translation_key, EntityIcons())
        value = entity_state.state
        try:
            number: float | None = float(value)
        except ValueError:
            number = None
        highest = max(
            (
                float(key)
                for key in icons.get("range", {})
                if number is not None and float(key) <= number
            ),
            default=None,
        )
        # The frontend finds that range's icon by the number as JavaScript writes it
        in_range = (
            None
            if highest is None
            else icons["range"].get(
                str(int(highest)) if highest.is_integer() else str(highest)
            )
        )
        shown[entity_id] = (
            entity_state.attributes.get(ATTR_ICON)
            or icons.get("state", {}).get(value)
            or in_range
            or icons.get("default")
        )
    return shown


@pytest.mark.usefixtures("google", "replies")
async def test_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Add the speaker, its entities on every platform, and the actions."""
    await set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SPEAKER_ID), config_entry.entry_id
    )
    assert device is not None
    assert (device.name, device.manufacturer, device.model) == (
        SPEAKER_NAME,
        MANUFACTURER,
        "Nest Audio",
    )
    assert {
        entity.entity_id: entity.device_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    } == dict.fromkeys(STATES, device.id)
    assert {entity_id: state(hass, entity_id) for entity_id in STATES} == STATES
    assert hass.services.async_services_for_domain(DOMAIN).keys() == ACTIONS.keys()


@pytest.mark.parametrize("platform", PLATFORMS)
def test_platform_sets_parallel_updates(platform: str) -> None:
    """Tell Home Assistant how many of the platform's updates and actions may run at once.

    Home Assistant's quality scale asks every platform to set it, and doesn't check
    a custom integration.
    """
    assert isinstance(
        import_module(f"custom_components.google_home.{platform}").PARALLEL_UPDATES, int
    )


@pytest.mark.usefixtures("google", "replies")
async def test_unload(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Stop the speaker's entities when the entry is unloaded."""
    await set_up(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    # Home Assistant shows the registered entities of an entry that isn't loaded
    # as unavailable, and marks them as restored
    for entity_id in STATES:
        entity_state = hass.states.get(entity_id)
        assert entity_state is not None
        assert (entity_state.state, entity_state.attributes.get("restored")) == (
            STATE_UNAVAILABLE,
            True,
        )


@pytest.mark.usefixtures("google", "replies")
async def test_platform_fails_to_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Show why the entry failed to unload when one of its platforms doesn't unload."""
    await set_up(hass, config_entry)

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert not await hass.config_entries.async_unload(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.FAILED_UNLOAD
    # Home Assistant's message, which it shows without the final period
    assert config_entry.reason == "Failed to unload one or more platforms"


async def test_master_token_rejected_at_setup(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock
) -> None:
    """Fail setup and ask to sign in again when Google rejects the master token."""
    google.side_effect = rejected()

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"].get("source") == SOURCE_REAUTH
    assert flow["context"].get("entry_id") == config_entry.entry_id


async def test_known_hosts_changed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
) -> None:
    """Load the entry again when known hosts change, as they're looked up only at setup.

    The speaker that mDNS didn't find is then found at its known host.
    """
    google.return_value = [kitchen_speaker(None)]
    replies[SPEAKER][INFO] = (
        HTTPStatus.OK,
        {"name": SPEAKER_NAME, "device_info": {"cloud_device_id": SPEAKER_CLOUD_ID}},
    )
    await set_up(hass, config_entry)
    assert state(hass, DEVICE_SENSOR) == STATE_UNAVAILABLE

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_KNOWN_HOSTS: [SPEAKER]}
    )
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    # Setup fetched Google's list again
    assert google.call_count == 2
    assert state(hass, DEVICE_SENSOR) == SPEAKER
    assert state(hass, ALARMS_SENSOR) == STATES[ALARMS_SENSOR]


@pytest.mark.usefixtures("replies")
async def test_update_interval_changed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Update the speaker at a changed interval without loading the entry again.

    The update that is already scheduled, at the default 15 seconds, keeps its time.
    """
    await set_up(hass, config_entry)

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 60}
    )
    await hass.async_block_till_done()

    assert await updated_at(hass, aioclient_mock, freezer) == [15, 75, 135]
    assert google.call_count == 1


@pytest.mark.usefixtures("google", "replies")
async def test_saved_update_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Update the speaker at the interval saved in the options, as after a restart."""
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 60}
    )
    await set_up(hass, config_entry)

    assert await updated_at(hass, aioclient_mock, freezer) == [60, 120, 180]


@pytest.mark.usefixtures("google")
async def test_turn_off_do_not_disturb(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Turn Do Not Disturb off on the speaker, and show it as soon as the speaker answers."""
    await set_up(hass, config_entry)
    aioclient_mock.mock_calls.clear()
    # The speaker answers with its new setting
    replies[SPEAKER][DND] = (HTTPStatus.OK, {"notifications_enabled": True})

    await hass.services.async_call(
        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: DND_SWITCH}, blocking=True
    )

    # The speaker's setting is whether notifications are enabled
    assert requests(aioclient_mock) == [
        ("POST", API_ENDPOINT_DO_NOT_DISTURB, {"notifications_enabled": True})
    ]
    assert state(hass, DND_SWITCH) == STATE_OFF


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize("load", [set_up, reload])
async def test_delete_alarm(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    load: Callable[[HomeAssistant, MockConfigEntry], Awaitable[None]],
) -> None:
    """Delete the alarm that the speaker has now, and show it gone once the speaker confirms.

    Also once the entry is loaded again.
    """
    await load(hass, config_entry)
    aioclient_mock.mock_calls.clear()
    replies[SPEAKER][DELETE] = (HTTPStatus.OK, {"success": True})

    await hass.services.async_call(
        DOMAIN,
        "delete_alarm",
        # Without it, the action updates the speaker again, whose fake answer
        # still lists the alarm
        {ATTR_ENTITY_ID: ALARMS_SENSOR, "alarm_id": ALARM_ID, "skip_refresh": True},
        blocking=True,
    )

    assert requests(aioclient_mock) == [
        ("GET", API_ENDPOINT_ALARMS, None),
        ("POST", API_ENDPOINT_ALARM_DELETE, {"ids": [ALARM_ID]}),
    ]
    alarms = hass.states.get(ALARMS_SENSOR)
    assert alarms is not None
    assert alarms.attributes["alarms"] == []


@pytest.mark.parametrize("action", ACTIONS)
async def test_action_fails_without_entry(hass: HomeAssistant, action: str) -> None:
    """Fail an action with Home Assistant's error while the integration has no entry.

    The integration registers its actions when it's set up, before any entry.
    """
    assert await async_setup_component(hass, DOMAIN, {})

    targets = {
        "entity": {ATTR_ENTITY_ID: ALARMS_SENSOR},
        "all": {ATTR_ENTITY_ID: ENTITY_MATCH_ALL},
    }
    assert await refusals(hass, action, targets) == dict.fromkeys(targets, NO_ENTRY)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    ("error", "entry_state"),
    [
        # Google rejected the master token: the user needs to sign in again
        (rejected(), ConfigEntryState.SETUP_ERROR),
        # An error the integration doesn't expect: Home Assistant tries again later
        (RuntimeError("Unexpected"), ConfigEntryState.SETUP_RETRY),
    ],
    ids=["setup error", "setup retry"],
)
async def test_action_fails_when_setup_fails(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    action: str,
    error: Exception,
    entry_state: ConfigEntryState,
) -> None:
    """Fail an action with Home Assistant's error while the entry couldn't be set up."""
    google.side_effect = error

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is entry_state
    targets = {
        "entity": {ATTR_ENTITY_ID: ALARMS_SENSOR},
        "all": {ATTR_ENTITY_ID: ENTITY_MATCH_ALL},
    }
    assert await refusals(hass, action, targets) == dict.fromkeys(targets, NOT_LOADED)


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("action", ACTIONS)
async def test_action_fails_after_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    aioclient_mock: AiohttpClientMocker,
    action: str,
) -> None:
    """Fail an action with Home Assistant's error after the entry is unloaded, without asking the speaker.

    Without the error, the action would find no sensor to run on and do nothing.
    """
    await set_up(hass, config_entry)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SPEAKER_ID), config_entry.entry_id
    )
    assert device is not None
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    aioclient_mock.mock_calls.clear()

    targets = {
        "entity": {ATTR_ENTITY_ID: ALARMS_SENSOR},
        "all": {ATTR_ENTITY_ID: ENTITY_MATCH_ALL},
        "device": {ATTR_DEVICE_ID: device.id},
    }
    assert await refusals(hass, action, targets) == dict.fromkeys(targets, NOT_LOADED)
    assert requests(aioclient_mock) == []


async def test_wrong_data_fails_first_without_entry(hass: HomeAssistant) -> None:
    """Fail an action with wrong data for that reason, also while there's no entry to run it."""
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            "delete_alarm",
            {ATTR_ENTITY_ID: ALARMS_SENSOR, "alarm_id": "alarm/wrong-format"},
            blocking=True,
        )
    assert error.value.translation_key == "invalid_alarm_id"
    with pytest.raises(probatio.Invalid, match="required key not provided"):
        await hass.services.async_call(
            DOMAIN, "delete_alarm", {ATTR_ENTITY_ID: ALARMS_SENSOR}, blocking=True
        )


async def test_script_stops_at_action_when_setup_fails(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock, tmp_path: Path
) -> None:
    """Load a script that uses an action while the entry isn't loaded, and stop it there.

    Unless the step continues on error, which covers Home Assistant's error.
    """
    # Where the script integration adds its blueprints
    hass.config.config_dir = str(tmp_path)
    google.side_effect = rejected()
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    next_steps = async_mock_service(hass, "test", "next_step")
    step = {
        "action": f"{DOMAIN}.delete_all_alarms",
        "target": {ATTR_ENTITY_ID: ALARMS_SENSOR},
    }
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "stops": {"sequence": [step, {"action": "test.next_step"}]},
                "continues": {
                    "sequence": [
                        {**step, "continue_on_error": True},
                        {"action": "test.next_step"},
                    ]
                },
            }
        },
    )

    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call("script", "stops", blocking=True)
    assert error.value.translation_key == NOT_LOADED[1]
    assert not next_steps
    await hass.services.async_call("script", "continues", blocking=True)
    assert len(next_steps) == 1


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("platform", PLATFORMS)
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    platform: str,
) -> None:
    """Name the speaker's entities and give them their attributes, one platform at a time."""
    with patch("custom_components.google_home.PLATFORMS", [platform]):
        await set_up(hass, config_entry)
        await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize("notifications_enabled", [False, True])
async def test_icons(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    replies: Replies,
    notifications_enabled: bool,
) -> None:
    """Show each entity's icon from icons.json, with Do Not Disturb on and off."""
    replies[SPEAKER][DND] = (
        HTTPStatus.OK,
        {"notifications_enabled": notifications_enabled},
    )
    await set_up(hass, config_entry)

    assert state(hass, DND_SWITCH) == (STATE_OFF if notifications_enabled else STATE_ON)
    assert await shown_icons(hass, entity_registry) == ICONS


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("volume", "icon"),
    [
        (0, "mdi:volume-off"),
        (1, "mdi:volume-low"),
        (30, "mdi:volume-low"),
        (31, "mdi:volume-medium"),
        (60, "mdi:volume-medium"),
        (61, "mdi:volume-high"),
        (100, "mdi:volume-high"),
    ],
)
async def test_alarm_volume_icon(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    replies: Replies,
    volume: int,
    icon: str,
) -> None:
    """Show the alarm volume as off at 0%, low up to 30%, medium up to 60% and high above."""
    # The speaker answers with the volume from 0 to 1
    replies[SPEAKER][VOLUME] = (HTTPStatus.OK, {"volume": volume / 100})
    await set_up(hass, config_entry)

    assert state(hass, VOLUME_NUMBER) == str(volume)
    assert (await shown_icons(hass, entity_registry))[VOLUME_NUMBER] == icon
