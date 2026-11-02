"""Tests for the integration's section in Home Assistant's System information.

Home Assistant's system_health component finds the integration's platform and asks it
for the section, as when the user opens System information. As in test_setup, only
glocaltokens, mDNS, the speakers and the two Google hosts that the section checks are
faked. Each test compares the whole section, so nothing else, such as a name, an
address or Google's reason for an error, can be in it.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import Mock, patch

from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, get_system_health_info

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.const import DOMAIN

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components import system_health
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component

from .conftest import BEDROOM, BEDROOM_ID, SPEAKER_ID, Replies, kitchen_speaker
from .test_coordinators import (
    KITCHEN_DEVICE,
    REJECTING,
    STARTING,
    runtime,
    update_account,
)
from .test_missing_devices import answered, found, rejected
from .test_polling_off import set_up_without_polling
from .test_setup import set_up, state
from .test_unsupported_devices import SPEAKER, SUPPORTED, Reply

# pylint: enable=wrong-import-order

# Where the integration signs in, and the host of the device list, which answer a
# plain request with "method not allowed" and "not found"
SIGN_IN_HOST = "android.clients.google.com"
DEVICE_LIST_HOST = "googlehomefoyer-pa.googleapis.com"
REACH_HELP = "https://ha-google-home.pages.dev/troubleshooting/#couldnt-reach-google"
SIGN_IN_HELP = "https://ha-google-home.pages.dev/troubleshooting/#sign-in-again"
REACHABLE = {"can_reach_sign_in": "ok", "can_reach_device_list": "ok"}
# The options of an entry that is set up as the config flow saves it
DEFAULT_OPTIONS = {"polling": True, "bluetooth_tracking": False}
# What a speaker answers while it doesn't answer at all, and with a server error
SILENT: dict[str, Reply] = dict.fromkeys(SUPPORTED, TimeoutError())
FAILING: dict[str, Reply] = dict.fromkeys(SUPPORTED, HTTPStatus.INTERNAL_SERVER_ERROR)
# The time Home Assistant's clock shows in these tests
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
# How long the list waits to be fetched again after the first failed fetch
FIRST_RETRY_DELAY = 60


@pytest.fixture(autouse=True)
async def fixture_system_health(
    hass: HomeAssistant, replies: Replies, freezer: FrozenDateTimeFactory
) -> None:
    """Set up System information, with Google's hosts answering, at NOW."""
    freezer.move_to(NOW)
    replies[SIGN_IN_HOST] = {"auth": HTTPStatus.METHOD_NOT_ALLOWED}
    replies[DEVICE_LIST_HOST] = {"": HTTPStatus.NOT_FOUND}
    assert await async_setup_component(hass, "system_health", {})


async def section(hass: HomeAssistant) -> dict[str, object]:
    """Return the integration's section, with the checks that run in the background done."""
    info = await get_system_health_info(hass, DOMAIN)
    return {
        key: await value if asyncio.iscoroutine(value) else value
        for key, value in info.items()
    }


async def refresh(hass: HomeAssistant, entry: MockConfigEntry, times: int = 1) -> None:
    """Update the kitchen speaker this many times, as its update interval does."""
    for _ in range(times):
        await runtime(entry).devices[SPEAKER_ID].async_refresh()
    await hass.async_block_till_done()


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    ("polling_off", "options", "shown"),
    [
        pytest.param(False, {}, DEFAULT_OPTIONS, id="defaults"),
        pytest.param(
            True,
            {"bluetooth_tracking": True},
            {"polling": False, "bluetooth_tracking": True},
            id="polling-off-bluetooth-on",
        ),
    ],
)
async def test_section_with_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    polling_off: bool,
    options: dict[str, object],
    shown: dict[str, bool],
) -> None:
    """Show that Google answers, that the list was fetched, the options, and the counts."""
    hass.config_entries.async_update_entry(config_entry, options=options)
    if polling_off:
        await set_up_without_polling(hass, config_entry)
    else:
        await set_up(hass, config_entry)

    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **shown,
        "devices_listed": 2,
        "devices_not_answering": 0,
    }


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize("host", [SIGN_IN_HOST, DEVICE_LIST_HOST])
@pytest.mark.parametrize(
    ("error", "shown"),
    [
        pytest.param(ClientConnectionError(), "unreachable", id="unreachable"),
        pytest.param(TimeoutError(), "timeout", id="timeout"),
    ],
)
async def test_google_cant_be_reached(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    host: str,
    error: Exception,
    shown: str,
) -> None:
    """Show which of Google's hosts can't be reached, with a link to what to check."""
    await set_up(hass, config_entry)
    replies[host] = dict.fromkeys(replies[host], error)
    key = "can_reach_sign_in" if host == SIGN_IN_HOST else "can_reach_device_list"

    assert await section(hass) == {
        **REACHABLE,
        key: {"type": "failed", "error": shown, "more_info": REACH_HELP},
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }


@pytest.mark.parametrize(
    ("error", "entry_state"),
    [
        pytest.param(
            ClientConnectionError(), ConfigEntryState.SETUP_RETRY, id="unreachable"
        ),
        pytest.param(rejected(), ConfigEntryState.SETUP_ERROR, id="sign-in-rejected"),
    ],
)
async def test_only_checks_while_not_set_up(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    error: Exception,
    entry_state: ConfigEntryState,
) -> None:
    """Show only whether Google answers while setup fails, whatever made it fail."""
    google.side_effect = error

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is entry_state
    assert await section(hass) == REACHABLE


@pytest.mark.usefixtures("replies")
async def test_sign_in_rejected_until_fetch_works(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock, clock: Mock
) -> None:
    """Show that Google rejected the master token until a fetch works, also after a server error.

    Google lists the devices again every 20 minutes. While it rejects the master
    token, the list and its devices stay.
    """
    await set_up(hass, config_entry)
    rejected_section = {
        **REACHABLE,
        "device_list": {
            "type": "failed",
            "error": "sign-in rejected",
            "more_info": SIGN_IN_HELP,
        },
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }

    google.side_effect = rejected()
    clock.return_value = 20 * 60
    await update_account(hass, config_entry)
    assert await section(hass) == rejected_section

    google.side_effect = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    clock.return_value = 40 * 60
    await update_account(hass, config_entry)
    assert await section(hass) == rejected_section

    google.side_effect = None
    clock.return_value = 60 * 60
    await update_account(hass, config_entry)
    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }


@pytest.mark.usefixtures("replies")
@pytest.mark.parametrize("polling_off", [False, True], ids=["polling", "polling-off"])
async def test_retry_not_before_while_list_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    polling_off: bool,
) -> None:
    """Show when the list may be fetched again after setup couldn't fetch it, without counts.

    Setup goes on without devices when Google is busy. Its fetch started at 0 s, so
    the next one waits until 60 s. Once that has passed, nothing says when it runs:
    an update starts it, and with polling off only one that something asks for.
    """
    google.side_effect = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    if polling_off:
        await set_up_without_polling(hass, config_entry)
    else:
        await set_up(hass, config_entry)
    unknown = {
        **REACHABLE,
        "device_list": "not fetched",
        **DEFAULT_OPTIONS,
        "polling": not polling_off,
    }

    clock.return_value = FIRST_RETRY_DELAY - 0.5
    assert await section(hass) == {
        **REACHABLE,
        "device_list": "not fetched",
        "retry_not_before": NOW + timedelta(seconds=0.5),
        **DEFAULT_OPTIONS,
        "polling": not polling_off,
    }

    clock.return_value = FIRST_RETRY_DELAY
    assert await section(hass) == unknown

    clock.return_value = FIRST_RETRY_DELAY + 10 * 60
    assert await section(hass) == unknown


@pytest.mark.usefixtures("replies")
async def test_known_list_after_fetch_fails(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock, clock: Mock
) -> None:
    """Keep showing the list as fetched, without a retry time, when Google can't be reached later.

    The list stays, and the next fetch is the one 20 minutes later, so the wait after a
    failed fetch doesn't apply.
    """
    await set_up(hass, config_entry)
    google.side_effect = ClientConnectionError()
    clock.return_value = 20 * 60
    await update_account(hass, config_entry)

    assert google.call_count == 2
    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }


@pytest.mark.usefixtures("replies")
async def test_empty_list(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock
) -> None:
    """Count no devices once a fetch has worked, even one that listed none."""
    google.return_value = []
    await set_up(hass, config_entry)

    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 0,
        "devices_not_answering": 0,
    }


@pytest.mark.usefixtures("replies")
async def test_device_without_address_not_answering(
    hass: HomeAssistant, config_entry: MockConfigEntry, google: Mock
) -> None:
    """Count a device without an address as not answering: it can't be asked."""
    google.return_value = [kitchen_speaker(), found("lounge", None)]
    await set_up(hass, config_entry)

    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 2,
        "devices_not_answering": 1,
    }


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("updates", "not_answering"),
    [
        # A speaker that restarts at night misses a few updates
        pytest.param([SILENT] * 4, 0, id="4-missed"),
        pytest.param([SILENT] * 5, 1, id="5-missed"),
        # A speaker that is starting answers "not found" for a while
        pytest.param([SILENT] * 5 + [STARTING], 1, id="not-found-after-5-missed"),
        pytest.param([SILENT] * 5 + [FAILING], 0, id="server-error-after-5-missed"),
        pytest.param([SILENT] * 4 + [STARTING], 0, id="not-found-after-4-missed"),
    ],
)
async def test_device_not_answering(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    updates: list[dict[str, Reply]],
    not_answering: int,
) -> None:
    """Count a device as not answering once it misses 5 updates in a row, until it answers other than "not found"."""
    await set_up(hass, config_entry)
    for reply in updates:
        replies[SPEAKER] = dict(reply)
        await refresh(hass, config_entry)

    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": not_answering,
    }


@pytest.mark.usefixtures("google")
async def test_rejected_token_answers_and_keeps_counts(
    hass: HomeAssistant, config_entry: MockConfigEntry, replies: Replies
) -> None:
    """Count a device that rejects its token as answering, and keep counting the list.

    Google gives it the same token again, so the list is to be fetched again, and
    until then isn't the one of a fetch that worked.
    """
    await set_up(hass, config_entry)
    replies[SPEAKER] = dict(SILENT)
    await refresh(hass, config_entry, times=5)

    replies[SPEAKER] = dict(REJECTING)
    await refresh(hass, config_entry)

    assert await section(hass) == {
        **REACHABLE,
        "device_list": "not fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }


@pytest.mark.usefixtures("google", "replies")
async def test_failed_update_isnt_counted(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Don't count a device whose update failed: that doesn't show it didn't answer."""
    await set_up(hass, config_entry)
    with patch.object(
        GlocaltokensApiClient, "update_device", side_effect=RuntimeError("Unexpected")
    ):
        await refresh(hass, config_entry)

    assert state(hass, KITCHEN_DEVICE) == STATE_UNAVAILABLE
    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }


@pytest.mark.usefixtures("two_speakers")
async def test_only_listed_devices_counted(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
) -> None:
    """Count only the devices in Google's list, not one it dropped that is kept a while."""
    await set_up(hass, config_entry)
    replies[BEDROOM] = dict(SILENT)
    for _ in range(5):
        await runtime(config_entry).devices[BEDROOM_ID].async_refresh()
    assert (await section(hass))["devices_not_answering"] == 1
    google.return_value = [kitchen_speaker()]
    clock.return_value = 20 * 60
    await update_account(hass, config_entry)

    assert BEDROOM_ID in runtime(config_entry).devices
    assert await section(hass) == {
        **REACHABLE,
        "device_list": "fetched",
        **DEFAULT_OPTIONS,
        "devices_listed": 1,
        "devices_not_answering": 0,
    }


async def test_home_assistant_shows_section(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
) -> None:
    """Show the section as Home Assistant puts it together, with its words for a failed check and the time in ISO format."""
    google.side_effect = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    await set_up(hass, config_entry)
    clock.return_value = FIRST_RETRY_DELAY - 30

    replies[DEVICE_LIST_HOST] = {"": ClientConnectionError()}
    info = await system_health.get_info(hass)

    assert info[DOMAIN] == {
        "can_reach_sign_in": "ok",
        "can_reach_device_list": "Failed: unreachable",
        "device_list": "not fetched",
        "retry_not_before": "2026-11-02T12:00:30+00:00",
        **DEFAULT_OPTIONS,
    }


async def test_every_row_has_a_label(hass: HomeAssistant) -> None:
    """Give each row a label that Home Assistant finds for the section, and no other."""
    labels = await async_get_translations(hass, "en", "system_health", {DOMAIN})

    prefix = f"component.{DOMAIN}.system_health.info."
    assert {key.removeprefix(prefix) for key in labels} == {
        "can_reach_sign_in",
        "can_reach_device_list",
        "device_list",
        "retry_not_before",
        "polling",
        "bluetooth_tracking",
        "devices_listed",
        "devices_not_answering",
    }
