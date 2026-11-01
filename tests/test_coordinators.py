"""Tests for the account's coordinator and each speaker's, running inside Home Assistant.

As in test_setup, only glocaltokens, mDNS and the speakers' answers are faked. Where
the order of the account's update and the speakers' updates matters, the tests run
them in that order rather than wait for their timers.
"""

import asyncio
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import Mock

from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
from glocaltokens.client import Device
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.account import KNOWN_HOSTS_INTERVAL
from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_DELETE,
    CONF_KNOWN_HOSTS,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    FETCH_DEVICES_INTERVAL,
)
from custom_components.google_home.coordinator import (
    GoogleAccountCoordinator,
    GoogleHomeDeviceCoordinator,
)
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.types import GoogleHomeData

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    DELETE,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    Held,
    Replies,
    bedroom_speaker,
    kitchen_speaker,
)
from .test_missing_devices import ALARM_ID, found, make_client, rejected, until
from .test_setup import set_up, state
from .test_unsupported_devices import (
    ALARMS,
    BUILD,
    DND,
    ENDPOINTS,
    INFO,
    OTHER,
    SPEAKER,
    SUPPORTED,
    UPDATE,
    VOLUME,
    Network,
    Reply,
)

# pylint: enable=wrong-import-order

KITCHEN_ALARMS = "sensor.kitchen_speaker_alarms"
KITCHEN_DEVICE = "sensor.kitchen_speaker_device"
BEDROOM_ALARMS = "sensor.bedroom_speaker_alarms"
BEDROOM_DEVICE = "sensor.bedroom_speaker_device"
BEDROOM_DND = "switch.bedroom_speaker_do_not_disturb"
EVERYTHING = [ALARMS, VOLUME, DND]
# What a speaker is asked after them when its firmware check is due, as at the first
# update of each new device object that it answers
FIRMWARE = [BUILD, UPDATE]
# What a speaker answers while it starts: "not found" for everything that needs
# its token
STARTING: dict[str, Reply] = dict.fromkeys(SUPPORTED, HTTPStatus.NOT_FOUND)
# What a speaker answers that rejects every token Google gives
REJECTING: dict[str, Reply] = {
    **dict.fromkeys(SUPPORTED, HTTPStatus.UNAUTHORIZED),
    # Its info needs no token
    INFO: SUPPORTED[INFO],
    BUILD: SUPPORTED[BUILD],
    UPDATE: SUPPORTED[UPDATE],
}
# An alarm at 1800000000 s, which a sensor shows in the tests' time zone US/Pacific
OTHER_ALARM = (
    HTTPStatus.OK,
    {"alarm": [{"id": ALARM_ID, "fire_time": 1800000000000, "status": 1}], "timer": []},
)
OTHER_ALARM_SHOWN = "2027-01-15T00:00:00-08:00"


def asked(aioclient_mock: AiohttpClientMocker) -> list[tuple[str, str]]:
    """Return the address and endpoint of each request sent since the last call, in order."""
    endpoints = {**ENDPOINTS, API_ENDPOINT_ALARM_DELETE: DELETE}
    requests = [
        (str(url.host), endpoints[url.path_qs.removeprefix("/")])
        for _, url, _, _ in aioclient_mock.mock_calls
    ]
    aioclient_mock.mock_calls.clear()
    return requests


def asked_by(requests: list[tuple[str, str]], address: str) -> list[str]:
    """Return what the speaker at this address was asked, in order."""
    return [endpoint for to, endpoint in requests if to == address]


def runtime(entry: MockConfigEntry) -> GoogleHomeData:
    """Return what the loaded entry keeps."""
    data: GoogleHomeData = entry.runtime_data
    return data


async def update_account(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Run the account's update, and the speaker updates it starts, to the end."""
    await runtime(entry).account.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.usefixtures("google", "two_speakers")
async def test_coordinators_of_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Keep the account's coordinator and one per speaker, each of the entry."""
    await set_up(hass, config_entry)

    data = runtime(config_entry)
    assert data.devices.keys() == {SPEAKER_ID, BEDROOM_ID}
    assert data.account.config_entry is config_entry
    assert all(
        coordinator.config_entry is config_entry
        for coordinator in data.devices.values()
    )


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    ("skip_refresh", "expected"),
    [(False, [ALARMS, DELETE, *EVERYTHING]), (True, [ALARMS, DELETE])],
)
async def test_delete_updates_only_its_speaker(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    skip_refresh: bool,
    expected: list[str],
) -> None:
    """Update only the speaker an alarm was deleted from, unless skip_refresh is set."""
    await set_up(hass, config_entry)
    asked(aioclient_mock)
    replies[SPEAKER][DELETE] = (HTTPStatus.OK, {"success": True})

    await hass.services.async_call(
        DOMAIN,
        "delete_alarm",
        {
            ATTR_ENTITY_ID: KITCHEN_ALARMS,
            "alarm_id": ALARM_ID,
            "skip_refresh": skip_refresh,
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    requests = asked(aioclient_mock)
    assert asked_by(requests, SPEAKER) == expected
    assert asked_by(requests, BEDROOM) == []


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    ("domain", "action", "targets", "updated"),
    [
        (
            DOMAIN,
            "refresh_devices",
            [KITCHEN_ALARMS, "sensor.kitchen_speaker_timers", KITCHEN_DEVICE],
            [SPEAKER, BEDROOM],
        ),
        ("homeassistant", "update_entity", [KITCHEN_ALARMS], [SPEAKER]),
    ],
)
async def test_refresh(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    domain: str,
    action: str,
    targets: list[str],
    updated: list[str],
) -> None:
    """Update every speaker once with refresh_devices, and only the sensor's with update_entity.

    refresh_devices updates also the speakers that its target doesn't cover, once
    each, however many sensors it targets.
    """
    await async_setup_component(hass, "homeassistant", {})
    await set_up(hass, config_entry)
    asked(aioclient_mock)

    await hass.services.async_call(
        domain, action, {ATTR_ENTITY_ID: targets}, blocking=True
    )
    await hass.async_block_till_done()

    requests = asked(aioclient_mock)
    for address in (SPEAKER, BEDROOM):
        assert asked_by(requests, address) == (EVERYTHING if address in updated else [])


@pytest.mark.usefixtures("two_speakers")
async def test_speaker_google_stops_listing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Show a speaker's entities as unavailable from the update that no longer lists it, and again once listed.

    Also while the speaker is being asked: that update doesn't bring back what
    Google no longer lists. Listed again, the same entities show its new data.
    """
    await set_up(hass, config_entry)
    entities = {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    }
    data = runtime(config_entry)
    held = Held(SUPPORTED[ALARMS])
    replies[BEDROOM][ALARMS] = held
    # Not a task that Home Assistant waits for
    poll = asyncio.create_task(data.devices[BEDROOM_ID].async_refresh())
    await held.asked.wait()

    # The scheduled fetch no longer lists the bedroom speaker
    google.return_value = [kitchen_speaker()]
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE
    assert state(hass, KITCHEN_ALARMS) != STATE_UNAVAILABLE
    asked(aioclient_mock)
    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: BEDROOM_DND}, blocking=True
    )
    assert asked(aioclient_mock) == []

    held.released.set()
    await poll
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE
    asked(aioclient_mock)
    # Until Google lists it again, its updates and the list's send it nothing
    await data.devices[BEDROOM_ID].async_refresh()
    await update_account(hass, config_entry)
    assert asked(aioclient_mock) == []
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE

    # Google lists it again, and it has another alarm now
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    replies[BEDROOM][ALARMS] = OTHER_ALARM
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    assert asked_by(asked(aioclient_mock), BEDROOM) == [*EVERYTHING, *FIRMWARE]
    assert state(hass, BEDROOM_ALARMS) == OTHER_ALARM_SHOWN
    assert {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    } == entities


async def test_speaker_added_in_google_home_app(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Ask a speaker that a scheduled fetch finds straight away, and add its entities without a reload.

    A speaker that doesn't answer gets only its device and Wi-Fi sensors and reboot
    button.
    """
    await set_up(hass, config_entry)
    asked(aioclient_mock)
    office = "10.0.0.4"
    google.return_value = [
        kitchen_speaker(),
        bedroom_speaker(),
        found("office", office, name="Office speaker"),
    ]
    replies[BEDROOM] = dict(SUPPORTED)
    replies[office] = dict.fromkeys(SUPPORTED, TimeoutError())

    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    requests = asked(aioclient_mock)
    assert asked_by(requests, BEDROOM) == [*EVERYTHING, *FIRMWARE]
    assert asked_by(requests, office) == [ALARMS, INFO]
    assert state(hass, BEDROOM_ALARMS) == "2023-11-14T14:13:20-08:00"
    added = {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
        if entry.entity_id.startswith(("sensor.office", "button.office"))
    }
    assert added == {
        "sensor.office_speaker_device",
        "sensor.office_speaker_wi_fi_network",
        "sensor.office_speaker_signal_strength",
        "button.office_speaker_reboot",
    }


async def test_known_host_answer_at_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Don't ask a speaker found at its known host at setup for its info again in its first update.

    Its info answered there, so it's available, though it's starting. Its next
    update asks for its info.
    """
    google.return_value = [kitchen_speaker(None)]
    replies[SPEAKER] = {
        **STARTING,
        INFO: (HTTPStatus.OK, {"device_info": {"cloud_device_id": SPEAKER_CLOUD_ID}}),
    }
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_KNOWN_HOSTS: [SPEAKER]}
    )

    await set_up(hass, config_entry)

    assert asked_by(asked(aioclient_mock), SPEAKER) == [INFO, *EVERYTHING, *FIRMWARE]
    device = hass.states.get("sensor.kitchen_speaker_device")
    assert device is not None
    assert device.attributes["available"] is True

    await runtime(config_entry).devices[SPEAKER_ID].async_refresh()
    assert asked_by(asked(aioclient_mock), SPEAKER) == [ALARMS, INFO, VOLUME, DND]


async def test_known_host_answer_after_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
) -> None:
    """Ask a speaker that a scheduled fetch finds at its known host straight away, without asking for its info again.

    Its known host didn't answer at setup, so the speaker had no address until then.
    """
    google.return_value = [kitchen_speaker(None)]
    replies[SPEAKER] = {**STARTING, INFO: TimeoutError()}
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_KNOWN_HOSTS: [SPEAKER]}
    )
    await set_up(hass, config_entry)
    assert asked_by(asked(aioclient_mock), SPEAKER) == [INFO]

    replies[SPEAKER][INFO] = (
        HTTPStatus.OK,
        {"device_info": {"cloud_device_id": SPEAKER_CLOUD_ID}},
    )
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    assert asked_by(asked(aioclient_mock), SPEAKER) == [INFO, *EVERYTHING, *FIRMWARE]
    device = hass.states.get("sensor.kitchen_speaker_device")
    assert device is not None
    assert device.attributes["available"] is True


async def test_known_hosts_asked_every_5_minutes_between_fetches(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
) -> None:
    """Look for a speaker without an address at the known hosts every 5 minutes, without asking Google.

    Neither known host answered at setup. Once the speaker's host answers, the speaker
    is asked straight away, without asking for its info again, and no host is asked
    after that, as no speaker needs an address. The other host never answers.
    """
    google.return_value = [kitchen_speaker(None)]
    replies[SPEAKER] = {**STARTING, INFO: TimeoutError()}
    replies[OTHER] = {INFO: TimeoutError()}
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_KNOWN_HOSTS: [SPEAKER, OTHER]}
    )
    await set_up(hass, config_entry)
    requests = asked(aioclient_mock)
    sent = {0: {host: asked_by(requests, host) for host in (SPEAKER, OTHER)}}

    # An update every 15 seconds, up to the scheduled fetch 20 minutes after setup's
    for seconds in range(15, FETCH_DEVICES_INTERVAL + 1, 15):
        if seconds == 3 * KNOWN_HOSTS_INTERVAL:
            replies[SPEAKER][INFO] = (
                HTTPStatus.OK,
                {"device_info": {"cloud_device_id": SPEAKER_CLOUD_ID}},
            )
        clock.return_value = seconds
        await update_account(hass, config_entry)
        if requests := asked(aioclient_mock):
            sent[seconds] = {
                host: asked_by(requests, host) for host in (SPEAKER, OTHER)
            }

    # Setup's fetch asks each host once, and nothing asks again before 5 minutes
    assert sent == {
        0: {SPEAKER: [INFO], OTHER: [INFO]},
        300: {SPEAKER: [INFO], OTHER: [INFO]},
        600: {SPEAKER: [INFO], OTHER: [INFO]},
        900: {SPEAKER: [INFO, *EVERYTHING, *FIRMWARE], OTHER: [INFO]},
    }
    # Setup's and the scheduled one
    assert google.call_count == 2
    device = hass.states.get(KITCHEN_DEVICE)
    assert device is not None
    assert device.state == SPEAKER
    assert device.attributes["available"] is True


async def test_failing_speaker_found_later_updates_on_its_own(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
) -> None:
    """Ask a speaker found after setup straight away, but not again at each update of the list while its update fails.

    Its timer comes without its fields, so it never gets data.
    """
    await set_up(hass, config_entry)
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    replies[BEDROOM] = {
        **SUPPORTED,
        ALARMS: (HTTPStatus.OK, {"alarm": [], "timer": [{}]}),
    }
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)
    assert asked_by(asked(aioclient_mock), BEDROOM) == [ALARMS]

    await update_account(hass, config_entry)

    assert asked_by(asked(aioclient_mock), BEDROOM) == []


async def test_speaker_found_later_asked_once_while_first_update_runs(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Ask a speaker found after setup once, however many updates of the list come while that first update waits for it.

    Then it updates at its interval.
    """
    await set_up(hass, config_entry)
    held = Held(SUPPORTED[ALARMS])
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    replies[BEDROOM] = {**SUPPORTED, ALARMS: held}
    data = runtime(config_entry)
    clock.return_value = FETCH_DEVICES_INTERVAL
    await data.account.async_refresh()
    await held.asked.wait()
    for seconds in (1, 2, 3):
        clock.return_value = FETCH_DEVICES_INTERVAL + seconds
        await data.account.async_refresh()

    held.released.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert asked_by(asked(aioclient_mock), BEDROOM) == [*EVERYTHING, *FIRMWARE]

    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert asked_by(asked(aioclient_mock), BEDROOM) == EVERYTHING


async def test_speaker_listed_again_while_old_update_runs(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
) -> None:
    """Ask a speaker listed again once, after the update of its earlier object ends.

    A scheduled fetch found the speaker after setup. Google stops listing it and lists
    it again while its next update waits for it, and more updates of the list come
    before that update ends. The earlier update shows nothing; the one for the speaker
    listed again shows its data.
    """
    await set_up(hass, config_entry)
    data = runtime(config_entry)
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    replies[BEDROOM] = dict(SUPPORTED)
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)
    assert asked_by(asked(aioclient_mock), BEDROOM) == [*EVERYTHING, *FIRMWARE]
    held = Held(SUPPORTED[ALARMS])
    replies[BEDROOM][ALARMS] = held
    # Not a task that Home Assistant waits for
    poll = asyncio.create_task(data.devices[BEDROOM_ID].async_refresh())
    await held.asked.wait()

    google.return_value = [kitchen_speaker()]
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    await data.account.async_refresh()
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    for seconds in (0, 1, 2):
        clock.return_value = 3 * FETCH_DEVICES_INTERVAL + seconds
        await data.account.async_refresh()
    replies[BEDROOM][ALARMS] = OTHER_ALARM
    asked(aioclient_mock)
    held.released.set()
    await poll
    await hass.async_block_till_done(wait_background_tasks=True)

    # The rest of the earlier update, without a firmware check, as Google's list has
    # replaced its device object, then one update of the speaker listed again, with
    # its first check
    assert asked_by(asked(aioclient_mock), BEDROOM) == [
        VOLUME,
        DND,
        *EVERYTHING,
        *FIRMWARE,
    ]
    assert state(hass, BEDROOM_ALARMS) == OTHER_ALARM_SHOWN


@pytest.mark.usefixtures("google", "two_speakers")
async def test_one_speaker_failing_leaves_the_others(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Make only a speaker's entities unavailable when its update fails unexpectedly.

    Here its timer comes without its fields. The other speaker keeps updating.
    """
    await set_up(hass, config_entry)
    replies[BEDROOM][ALARMS] = (HTTPStatus.OK, {"alarm": [], "timer": [{}]})
    data = runtime(config_entry)

    await data.devices[BEDROOM_ID].async_refresh()
    asked(aioclient_mock)
    await data.devices[SPEAKER_ID].async_refresh()

    assert asked_by(asked(aioclient_mock), SPEAKER) == EVERYTHING
    assert state(hass, BEDROOM_ALARMS) == STATE_UNAVAILABLE
    assert state(hass, KITCHEN_ALARMS) == "2023-11-14T14:13:20-08:00"


@pytest.mark.usefixtures("two_speakers")
async def test_rejected_token_at_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    entity_registry: er.EntityRegistry,
) -> None:
    """Set up with every speaker when one rejects its token, and get it a new one at the next update.

    Setup's fetch is the one of its update, so the speaker gets no fetch of its own,
    and nothing asks to sign in again. The next update of the list fetches it.
    """
    replies[BEDROOM] = dict(REJECTING)

    await set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert google.call_count == 1
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    assert state(hass, KITCHEN_ALARMS) != STATE_UNAVAILABLE
    assert state(hass, BEDROOM_DEVICE) == BEDROOM
    assert (
        entity_registry.async_get_entity_id("sensor", DOMAIN, "bedroom/alarms") is None
    )
    data = runtime(config_entry)
    assert not data.client.google_devices_fetched

    # The token in the list fetched next is one the speaker accepts
    def new_token(*_args: object, **_kwargs: object) -> list[Device]:
        replies[BEDROOM] = dict(SUPPORTED)
        return [kitchen_speaker(), bedroom_speaker()]

    google.side_effect = new_token
    await update_account(hass, config_entry)
    assert google.call_count == 2
    await data.devices[BEDROOM_ID].async_refresh()
    await hass.async_block_till_done()

    assert state(hass, BEDROOM_ALARMS) == "2023-11-14T14:13:20-08:00"


@pytest.mark.usefixtures("two_speakers")
async def test_ask_to_sign_in_after_speaker_update(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Ask to sign in again as soon as a speaker's update finds that Google rejects the master token.

    The speaker rejects its token, in an update of the list without a fetch yet, so
    its update fetches the list. The other speaker keeps updating with its token.
    """
    await async_setup_component(hass, "homeassistant", {})
    await set_up(hass, config_entry)
    # An update that doesn't fetch the list, which is known
    await update_account(hass, config_entry)
    replies[BEDROOM] = dict(REJECTING)
    google.side_effect = rejected()

    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {ATTR_ENTITY_ID: BEDROOM_ALARMS},
        blocking=True,
    )

    assert google.call_count == 2
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"].get("source") == SOURCE_REAUTH
    asked(aioclient_mock)
    await runtime(config_entry).devices[SPEAKER_ID].async_refresh()
    assert asked_by(asked(aioclient_mock), SPEAKER) == EVERYTHING
    assert state(hass, KITCHEN_ALARMS) != STATE_UNAVAILABLE


@pytest.mark.usefixtures("two_speakers")
async def test_action_leaves_sign_in_to_next_update(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
) -> None:
    """Ask to sign in again at the next update after an action finds that Google rejects the master token."""
    await set_up(hass, config_entry)
    await update_account(hass, config_entry)
    replies[BEDROOM][DND] = HTTPStatus.UNAUTHORIZED
    google.side_effect = rejected()

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: BEDROOM_DND}, blocking=True
        )
    await hass.async_block_till_done()

    assert google.call_count == 2
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    await runtime(config_entry).devices[SPEAKER_ID].async_refresh()
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"].get("source") == SOURCE_REAUTH


@pytest.mark.usefixtures("two_speakers")
async def test_interval_of_speaker_added_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock, clock: Mock
) -> None:
    """Update a speaker that a fetch finds after the interval changed at the new interval."""
    google.return_value = [kitchen_speaker()]
    await set_up(hass, config_entry)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 60}
    )
    await hass.async_block_till_done()

    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    data = runtime(config_entry)
    assert [
        data.account.update_interval,
        *(coordinator.update_interval for coordinator in data.devices.values()),
    ] == [timedelta(seconds=60)] * 3


async def test_nothing_asked_after_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Stop asking every speaker once the entry unloads.

    Also a speaker found after setup, whose first update is still waiting for it.
    """
    await set_up(hass, config_entry)
    held = Held(SUPPORTED[ALARMS])
    replies[BEDROOM] = {**SUPPORTED, ALARMS: held}
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    clock.return_value = FETCH_DEVICES_INTERVAL
    await runtime(config_entry).account.async_refresh()
    await held.asked.wait()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    asked(aioclient_mock)
    for _ in range(12):
        freezer.tick(timedelta(seconds=15))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert asked(aioclient_mock) == []


def coordinators(
    hass: HomeAssistant, entry: MockConfigEntry, client: GlocaltokensApiClient
) -> GoogleHomeData:
    """Give the entry the client and the account's coordinator, as setup does before its first update.

    The entry isn't loaded, so the account's updates leave each speaker's update to
    the test.
    """
    account = GoogleAccountCoordinator(hass, entry, client, timedelta(seconds=15))
    entry.runtime_data = GoogleHomeData(client, account, {})
    return runtime(entry)


async def test_update_joining_action_fetch_uses_its_known_host(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Use the known host found by a fetch that an action started and the account's update waited for.

    The list is unknown, so the update would otherwise fetch it itself. The fetch
    finds the bedroom speaker at its known host, which answers with its info once.
    Its next update doesn't ask for its info again, though it's starting; the one
    after does.
    """
    network = Network()
    network.replies[SPEAKER] = dict(REJECTING)
    network.replies[BEDROOM] = {
        **STARTING,
        INFO: (HTTPStatus.OK, {"device_info": {"cloud_device_id": "device1"}}),
    }
    google_answers = asyncio.Event()
    client, glocaltokens = make_client(
        SPEAKER,
        None,
        session=network.session,
        google_answers_when=google_answers.is_set,
    )
    client.known_hosts = [BEDROOM]
    client.google_devices_fetched = False
    kitchen = client.google_devices[0]
    data = coordinators(hass, config_entry, client)

    action = asyncio.create_task(client.set_do_not_disturb(kitchen, enable=True))
    # The kitchen speaker rejected the action's token, whose fetch waits for Google
    await until(lambda: network.asked(SPEAKER) == [DND])
    update = asyncio.create_task(data.account.async_refresh())
    await asyncio.sleep(0)
    google_answers.set()
    await asyncio.gather(action, update, return_exceptions=True)

    assert glocaltokens.get_google_devices.call_count == 1
    assert network.asked(BEDROOM) == [INFO]
    bedroom = data.devices["device1"]
    await bedroom.async_refresh()
    assert network.asked(BEDROOM) == [*EVERYTHING, *FIRMWARE]
    assert bedroom.data is not None
    assert bedroom.data.reachable
    await bedroom.async_refresh()
    assert network.asked(BEDROOM) == [ALARMS, INFO, VOLUME, DND]


async def test_update_joining_failed_fetch_uses_no_known_host(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Hand over no known host when the fetch that the account's update waited for fails.

    An earlier fetch found the bedroom speaker at its known host. The update must not
    hand that answer over again, so the speaker's next update asks for its info.
    """
    network = Network()
    network.replies[SPEAKER] = dict(REJECTING)
    network.replies[BEDROOM] = {
        **STARTING,
        INFO: (HTTPStatus.OK, {"device_info": {"cloud_device_id": "device1"}}),
    }
    google_answers = asyncio.Event()
    google_answers.set()
    client, glocaltokens = make_client(
        SPEAKER,
        None,
        session=network.session,
        google_answers_when=google_answers.is_set,
    )
    client.known_hosts = [BEDROOM]
    client.google_devices_fetched = False
    kitchen = client.google_devices[0]
    data = coordinators(hass, config_entry, client)
    await data.account.async_refresh()
    bedroom = data.devices["device1"]
    await bedroom.async_refresh()
    assert network.asked(BEDROOM) == [INFO, *EVERYTHING, *FIRMWARE]
    # A round without a fetch, so the action may fetch
    await data.account.async_refresh()

    glocaltokens.get_google_devices.side_effect = ClientConnectionError
    google_answers.clear()
    action = asyncio.create_task(client.set_do_not_disturb(kitchen, enable=True))
    await until(lambda: network.asked(SPEAKER) == [DND])
    # The list is unknown, so the update waits for the action's fetch
    client.google_devices_fetched = False
    update = asyncio.create_task(data.account.async_refresh())
    await asyncio.sleep(0)
    google_answers.set()
    await asyncio.gather(action, update, return_exceptions=True)

    assert glocaltokens.get_google_devices.call_count == 2
    await bedroom.async_refresh()
    assert network.asked(BEDROOM) == [ALARMS, INFO, VOLUME, DND]


@pytest.mark.parametrize("change", [None, "object", "address"])
async def test_known_host_answer_only_for_its_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, change: str | None
) -> None:
    """Use a known host's answer once, and only for the device found there, at that address.

    Google may list the device again as a new object, or mDNS may give it another
    address, before its update. Then its update asks for its info.
    """
    other = "10.0.0.5"
    network = Network()
    network.replies[BEDROOM] = dict(STARTING)
    network.replies[other] = dict(STARTING)
    client, _ = make_client(BEDROOM, session=network.session)
    [device] = client.google_devices
    data = coordinators(hass, config_entry, client)
    coordinator = GoogleHomeDeviceCoordinator(
        hass, config_entry, client, device, timedelta(seconds=15)
    )
    coordinator.info_answered = (device, BEDROOM)
    address = BEDROOM
    if change == "object":
        client.google_devices = [
            GoogleHomeDevice(device.device_id, device.name, "token", BEDROOM)
        ]
    elif change == "address":
        address = device.ip_address = other
    data.devices[device.device_id] = coordinator

    await coordinator.async_refresh()
    assert network.asked(address) == (
        # Only the known host's answer makes the starting speaker reachable
        [*EVERYTHING, *FIRMWARE] if change is None else [ALARMS, INFO, VOLUME, DND]
    )
    await coordinator.async_refresh()
    assert network.asked(address) == [ALARMS, INFO, VOLUME, DND]
