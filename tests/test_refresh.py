"""Tests for refresh_devices: which targets it runs on and who may run it.

It updates every speaker once, also when the sensors it targets are unavailable,
which Home Assistant's entity actions skip. As in test_setup, only glocaltokens,
mDNS and the speakers' answers are faked.
"""

import asyncio

import pytest
from pytest_homeassistant.common import MockConfigEntry, MockUser
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import DOMAIN, UNANSWERED_UPDATES

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    CONF_EXCLUDE,
    ENTITY_MATCH_ALL,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers import device_registry as dr

from .conftest import BEDROOM, BEDROOM_ID, SPEAKER_ID, Replies
from .test_coordinators import (
    BEDROOM_ALARMS,
    BEDROOM_DND,
    KITCHEN_ALARMS,
    asked,
    asked_by,
    runtime,
)
from .test_disabled_devices import kitchen_device, set_disabled
from .test_offline_devices import SILENT
from .test_setup import set_up, state
from .test_unsupported_devices import ALARMS, SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order

# Each speaker's alarms sensor and ID, by address
ALARMS_SENSORS = {SPEAKER: KITCHEN_ALARMS, BEDROOM: BEDROOM_ALARMS}
ADDRESS_IDS = {SPEAKER: SPEAKER_ID, BEDROOM: BEDROOM_ID}
# An action's target, by entity_id or device_id
type Target = dict[str, str | list[str]]


async def go_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry, replies: Replies, *addresses: str
) -> None:
    """Make these speakers miss enough updates in a row that their entities show unavailable.

    They answer again afterwards, though nothing has asked them yet.
    """
    for address in addresses:
        replies[address] = dict(SILENT)
    for _ in range(UNANSWERED_UPDATES):
        await asyncio.gather(
            *(runtime(entry).devices[ADDRESS_IDS[a]].async_refresh() for a in addresses)
        )
    for address in addresses:
        replies[address] = dict(SUPPORTED)
        assert state(hass, ALARMS_SENSORS[address]) == STATE_UNAVAILABLE


def target_data(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, target: Target
) -> Target:
    """Return the action's target, with each speaker's device ID from the registry."""
    if ATTR_DEVICE_ID not in target:
        return target
    devices = [
        device_registry.async_get_device_by_identifier(
            (DOMAIN, device_id), entry.entry_id
        )
        for device_id in target[ATTR_DEVICE_ID]
    ]
    return {ATTR_DEVICE_ID: [device.id for device in devices if device is not None]}


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    ("unavailable", "target"),
    [
        pytest.param([BEDROOM], {ATTR_ENTITY_ID: BEDROOM_ALARMS}, id="sensor"),
        pytest.param(
            [SPEAKER, BEDROOM],
            {ATTR_ENTITY_ID: [KITCHEN_ALARMS, BEDROOM_ALARMS]},
            id="all sensors",
        ),
        pytest.param([BEDROOM], {ATTR_DEVICE_ID: [BEDROOM_ID]}, id="device"),
        pytest.param(
            [SPEAKER, BEDROOM], {ATTR_ENTITY_ID: ENTITY_MATCH_ALL}, id="entity_id all"
        ),
    ],
)
async def test_refresh_unavailable_speakers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    unavailable: list[str],
    target: Target,
) -> None:
    """Update every speaker with refresh_devices also when the sensors it targets are unavailable.

    Home Assistant's entity actions skip unavailable sensors. A speaker that answers
    again shows what it showed before it stopped answering.
    """
    await set_up(hass, config_entry)
    shown = {sensor: state(hass, sensor) for sensor in ALARMS_SENSORS.values()}
    await go_unavailable(hass, config_entry, replies, *unavailable)
    asked(aioclient_mock)

    await hass.services.async_call(
        DOMAIN,
        "refresh_devices",
        target_data(device_registry, config_entry, target),
        blocking=True,
    )
    await hass.async_block_till_done()

    requests = asked(aioclient_mock)
    assert all(ALARMS in asked_by(requests, address) for address in ALARMS_SENSORS)
    assert {sensor: state(hass, sensor) for sensor in ALARMS_SENSORS.values()} == shown


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    "target",
    [
        pytest.param({ATTR_ENTITY_ID: BEDROOM_ALARMS}, id="sensor"),
        pytest.param({ATTR_DEVICE_ID: [BEDROOM_ID]}, id="device"),
    ],
)
async def test_refresh_speaker_silent_since_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    target: Target,
) -> None:
    """Update a speaker that hasn't answered since setup when the target covers its sensors.

    As after Home Assistant restarts while the speaker is unplugged: its alarms
    sensor isn't added until it answers, and shows unavailable meanwhile.
    """
    await set_up(hass, config_entry)
    shown = state(hass, BEDROOM_ALARMS)
    replies[BEDROOM] = dict(SILENT)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE
    replies[BEDROOM] = dict(SUPPORTED)
    asked(aioclient_mock)

    await hass.services.async_call(
        DOMAIN,
        "refresh_devices",
        target_data(device_registry, config_entry, target),
        blocking=True,
    )
    await hass.async_block_till_done()

    assert ALARMS in asked_by(asked(aioclient_mock), BEDROOM)
    assert state(hass, BEDROOM_ALARMS) == shown


@pytest.mark.usefixtures("google", "two_speakers")
async def test_refresh_all_except_every_speaker(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Update no speaker with entity_id: all when its exclude block covers every speaker."""
    await set_up(hass, config_entry)
    asked(aioclient_mock)
    speakers = target_data(
        device_registry, config_entry, {ATTR_DEVICE_ID: [SPEAKER_ID, BEDROOM_ID]}
    )

    await hass.services.async_call(
        DOMAIN,
        "refresh_devices",
        {ATTR_ENTITY_ID: ENTITY_MATCH_ALL, CONF_EXCLUDE: speakers},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert asked(aioclient_mock) == []


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    ("target", "missing"),
    [
        pytest.param(
            {ATTR_ENTITY_ID: BEDROOM_DND},
            f"entities {BEDROOM_DND}",
            id="Google Home entity that isn't a sensor",
        ),
        pytest.param(
            {ATTR_ENTITY_ID: "sensor.outside"},
            "entities sensor.outside",
            id="other integration's sensor",
        ),
        pytest.param(
            {ATTR_DEVICE_ID: "no-such-device"},
            "devices no-such-device",
            id="missing device",
        ),
    ],
)
async def test_refresh_needs_google_home_sensor(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    target: Target,
    missing: str,
) -> None:
    """Update no speaker when the target covers no Google Home sensor, also while one is unavailable.

    Home Assistant's warning names what the target covers instead.
    """
    await set_up(hass, config_entry)
    hass.states.async_set("sensor.outside", "12")
    await go_unavailable(hass, config_entry, replies, BEDROOM)
    asked(aioclient_mock)

    await hass.services.async_call(DOMAIN, "refresh_devices", target, blocking=True)
    await hass.async_block_till_done()

    assert asked(aioclient_mock) == []
    assert f"Referenced {missing} are missing or not currently available" in (
        caplog.text
    )
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE


@pytest.mark.usefixtures("google", "two_speakers")
async def test_refresh_needs_enabled_sensor(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Update no speaker when the target covers only a disabled speaker's sensors.

    Home Assistant disables a device's entities with it.
    """
    await set_up(hass, config_entry)
    kitchen = kitchen_device(device_registry, config_entry)
    await set_disabled(hass, device_registry, kitchen.id, disabled=True)
    asked(aioclient_mock)

    await hass.services.async_call(
        DOMAIN, "refresh_devices", {ATTR_ENTITY_ID: KITCHEN_ALARMS}, blocking=True
    )
    await hass.async_block_till_done()

    assert asked(aioclient_mock) == []


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    ("policy", "target", "refused"),
    [
        # Read-only users can't control any entity
        pytest.param(
            None, {ATTR_ENTITY_ID: BEDROOM_ALARMS}, BEDROOM_ALARMS, id="read-only"
        ),
        # Refused for whichever of the speaker's entities is checked first
        pytest.param(
            None,
            {ATTR_DEVICE_ID: [BEDROOM_ID]},
            ".bedroom_speaker_",
            id="read-only device",
        ),
        pytest.param(
            None, {ATTR_ENTITY_ID: ENTITY_MATCH_ALL}, None, id="read-only all"
        ),
        pytest.param(
            {BEDROOM_ALARMS: True}, {ATTR_ENTITY_ID: BEDROOM_ALARMS}, None, id="control"
        ),
        pytest.param(
            {BEDROOM_ALARMS: True},
            {ATTR_ENTITY_ID: ENTITY_MATCH_ALL},
            None,
            id="control all",
        ),
        pytest.param(
            {BEDROOM_ALARMS: True},
            {ATTR_ENTITY_ID: [BEDROOM_ALARMS, KITCHEN_ALARMS]},
            KITCHEN_ALARMS,
            id="control of one target",
        ),
        # Also an entity that the action doesn't run on
        pytest.param(
            {BEDROOM_ALARMS: True},
            {ATTR_ENTITY_ID: [BEDROOM_ALARMS, BEDROOM_DND]},
            BEDROOM_DND,
            id="control of sensor but not switch",
        ),
    ],
)
async def test_refresh_needs_control_of_target(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    hass_read_only_user: MockUser,
    policy: dict[str, bool] | None,
    target: Target,
    refused: str | None,
) -> None:
    """Refuse a user who isn't an admin unless they may control everything the target covers.

    As Home Assistant's entity actions do, also while the targeted speaker is
    unavailable. With entity_id: all, only the sensors they may control count, so
    a read-only user updates nothing. Here they may control the bedroom's alarms
    sensor at most.
    """
    if policy is not None:
        hass_read_only_user.mock_policy({"entities": {"entity_ids": policy}})
    await set_up(hass, config_entry)
    shown = state(hass, BEDROOM_ALARMS)
    await go_unavailable(hass, config_entry, replies, BEDROOM)
    asked(aioclient_mock)
    data = target_data(device_registry, config_entry, target)
    context = Context(user_id=hass_read_only_user.id)

    if refused is None:
        await hass.services.async_call(
            DOMAIN, "refresh_devices", data, blocking=True, context=context
        )
    else:
        with pytest.raises(Unauthorized) as error:
            await hass.services.async_call(
                DOMAIN, "refresh_devices", data, blocking=True, context=context
            )
        assert refused in (error.value.entity_id or "")
    await hass.async_block_till_done()

    updated = policy is not None and refused is None
    requests = asked(aioclient_mock)
    assert {a: bool(asked_by(requests, a)) for a in ALARMS_SENSORS} == dict.fromkeys(
        ALARMS_SENSORS, updated
    )
    assert state(hass, BEDROOM_ALARMS) == (shown if updated else STATE_UNAVAILABLE)


@pytest.mark.usefixtures("google", "two_speakers")
async def test_refresh_refuses_unknown_user(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Refuse a call from a user that Home Assistant doesn't know, as its entity actions do."""
    await set_up(hass, config_entry)
    asked(aioclient_mock)

    with pytest.raises(UnknownUser):
        await hass.services.async_call(
            DOMAIN,
            "refresh_devices",
            {ATTR_ENTITY_ID: KITCHEN_ALARMS},
            blocking=True,
            context=Context(user_id="no-such-user"),
        )

    assert asked(aioclient_mock) == []
