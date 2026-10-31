"""Tests for the integration running inside Home Assistant.

Home Assistant sets up the entry, runs its updates and calls its actions. Only
glocaltokens, mDNS and the speaker's answers are faked, by the fixtures in conftest.py.
"""

from datetime import timedelta
from http import HTTPStatus
from importlib import import_module
from unittest.mock import Mock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
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
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import (
    DELETE,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    Replies,
    kitchen_speaker,
)
from .test_missing_devices import ALARM_ID, rejected
from .test_unsupported_devices import DND, INFO, SPEAKER

# pylint: enable=wrong-import-order

DEVICE_SENSOR = "sensor.kitchen_speaker_device"
ALARMS_SENSOR = "sensor.kitchen_speaker_alarms"
DND_SWITCH = "switch.kitchen_speaker_do_not_disturb"
# The speaker's entities and their states, as it answers in SUPPORTED: an alarm at
# 1700000000 s, 22:13:20 UTC, shown in the tests' time zone US/Pacific, no timer,
# which the timers sensor shows as unavailable, alarm volume 0.7, and notifications
# not enabled, which is Do Not Disturb on
STATES = {
    DEVICE_SENSOR: SPEAKER,
    ALARMS_SENSOR: "2023-11-14T14:13:20-08:00",
    "sensor.kitchen_speaker_timers": STATE_UNAVAILABLE,
    DND_SWITCH: STATE_ON,
    "number.kitchen_speaker_alarm_volume": "70",
    "button.kitchen_speaker_reboot": STATE_UNKNOWN,
}
ACTIONS = {
    "reboot_device",
    "delete_alarm",
    "delete_timer",
    "delete_all_alarms",
    "delete_all_timers",
    "refresh_devices",
}


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


def state(hass: HomeAssistant, entity_id: str) -> str:
    """Return the entity's state."""
    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    return entity_state.state


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
    assert hass.services.async_services_for_domain(DOMAIN).keys() == ACTIONS


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
async def test_delete_alarm(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Delete the alarm that the speaker has now, and show it gone once the speaker confirms."""
    await set_up(hass, config_entry)
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
