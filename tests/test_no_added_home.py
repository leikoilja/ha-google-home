"""Tests for the repair shown while no home's devices are added, running inside Home Assistant.

As in test_homes, the kitchen speaker is at home and the bedroom speaker in the
holiday house, and glocaltokens itself makes the device list from Google's home
graph. The options flow, reloads and the issue registry run through Home Assistant.
"""

import asyncio
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import Mock

from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module
from glocaltokens.exceptions import HomegraphError
import grpc  # type: ignore[import-untyped]
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.google_home.const import DOMAIN, ISSUE_NO_ADDED_HOME
from custom_components.google_home.exceptions import DeviceRequestFailed

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.registry import SAVE_DELAY
from homeassistant.helpers.translation import async_get_translations
from script.check_translations import placeholders

from .conftest import ForToken, Replies
from .test_coordinators import BEDROOM_ALARMS, KITCHEN_ALARMS, runtime, update_account

# The home_graph fixture is imported for pytest, which finds it here by its name
# pylint: disable-next=unused-import
from .test_homes import (
    ALARM_SHOWN,
    HOLIDAY_HOUSE,
    HOME,
    NEW_HOME,
    at_home,
    choose_homes,
    fixture_home_graph,  # noqa: F401
    graph,
    holiday_house,
    home,
)
from .test_polling_off import NEW_TOKEN, press_reboot, refresh_devices
from .test_removed_devices import KITCHEN_IN_HOME_GRAPH, fetch_list
from .test_setup import set_up, state
from .test_unsupported_devices import ALARMS, REBOOT, SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order


def repair(issue_registry: ir.IssueRegistry) -> ir.IssueEntry | None:
    """Return the repair that says no home's devices are added, if there is one."""
    return issue_registry.async_get_issue(DOMAIN, ISSUE_NO_ADDED_HOME)


async def shown_repair(hass: HomeAssistant, issue_registry: ir.IssueRegistry) -> str:
    """Return which repair says that no home's devices are added, by its text.

    It's a warning for the entry, with no fix, and its text is in English with each
    placeholder filled. The text links to the integration's page.
    """
    issue = repair(issue_registry)
    assert issue is not None and issue.active
    assert (
        issue.is_fixable,
        issue.severity,
        issue.config_entry_id,
        issue.translation_placeholders,
    ) == (
        False,
        ir.IssueSeverity.WARNING,
        hass.config_entries.async_entries(DOMAIN)[0].entry_id,
        {"integration_url": "/config/integrations/integration/google_home"},
    )
    text = await async_get_translations(hass, "en", "issues", [DOMAIN])
    prefix = f"component.{DOMAIN}.issues.{issue.translation_key}"
    assert {
        part: placeholders(text[f"{prefix}.{part}"])
        for part in ("title", "description")
    } == {"title": set(), "description": {"integration_url"}}
    assert issue.translation_key is not None
    return issue.translation_key


@pytest.mark.parametrize(
    ("join_or_select", "added"),
    [
        # Selecting the home left reloads the integration
        pytest.param(False, BEDROOM_ALARMS, id="select-home-left"),
        # A home joined later is added at the next fetch
        pytest.param(True, KITCHEN_ALARMS, id="join-home"),
    ],
)
async def test_repair_when_only_deselected_homes_left(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
    issue_registry: ir.IssueRegistry,
    join_or_select: bool,
    added: str,
) -> None:
    """Warn once Google's home graph has only deselected homes, until it has one whose devices are added.

    The account leaves the home whose devices were added, and only the deselected
    holiday house is left.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    await set_up(hass, config_entry)
    assert repair(issue_registry) is None

    home_graph.return_value = graph(holiday_house())
    await fetch_list(hass, config_entry, clock, 1)

    assert await shown_repair(hass, issue_registry) == "homes_deselected"

    if join_or_select:
        home_graph.return_value = graph(
            holiday_house(), home(NEW_HOME, "New home", KITCHEN_IN_HOME_GRAPH)
        )
        await fetch_list(hass, config_entry, clock, 2)
    else:
        await choose_homes(hass, config_entry, [HOLIDAY_HOUSE])

    assert repair(issue_registry) is None
    assert state(hass, added) == ALARM_SHOWN


@pytest.mark.parametrize(
    "polling", [pytest.param(True, id="polling"), pytest.param(False, id="no-polling")]
)
async def test_repair_while_google_reports_no_home(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
    issue_registry: ir.IssueRegistry,
    polling: bool,
) -> None:
    """Warn while Google reports no home for the account, until it reports one.

    The account then joins a home. With polling on, the next fetch adds its devices.
    With polling off, nothing fetches by itself, and the warning says to reload.
    """
    home_graph.return_value = graph()
    hass.config_entries.async_update_entry(
        config_entry, pref_disable_polling=not polling
    )
    await set_up(hass, config_entry)

    assert await shown_repair(hass, issue_registry) == "no_home"

    home_graph.return_value = graph(at_home())
    if polling:
        await fetch_list(hass, config_entry, clock, 1)
    else:
        assert await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert repair(issue_registry) is None
    assert state(hass, KITCHEN_ALARMS) == ALARM_SHOWN


@pytest.mark.parametrize(
    "answer",
    [
        # Google doesn't give the home graph
        pytest.param(
            HomegraphError(grpc.StatusCode.UNAVAILABLE, "Unavailable"),
            id="fetch-fails",
        ),
        # A home without an ID can't be excluded, so its devices are added
        pytest.param(
            graph(home("", "Home", KITCHEN_IN_HOME_GRAPH), holiday_house()),
            id="home-without-id",
        ),
        # An added home without devices still counts as added
        pytest.param(graph(home(HOME, "Home"), holiday_house()), id="no-devices"),
    ],
)
async def test_no_repair_unless_google_reports_no_added_home(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    issue_registry: ir.IssueRegistry,
    answer: HomeGraph | Exception,
) -> None:
    """Don't warn while the home graph is unknown, or has a home whose devices are added."""
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    if isinstance(answer, Exception):
        home_graph.side_effect = answer
    else:
        home_graph.return_value = answer

    await set_up(hass, config_entry)

    assert home_graph.await_count == 1
    assert repair(issue_registry) is None


async def test_repair_from_fetch_for_rejected_token(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    replies: Replies,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Warn after a fetch that a speaker's rejected token starts, even though the list is unknown then.

    With polling off, a refresh updates the account first, without fetching as the
    list isn't due. The kitchen speaker then rejects its token, and Google's answer to
    the fetch for a new one no longer has the kitchen's home, so it gets none. A
    later fetch that fails changes nothing.
    """
    hass.config_entries.async_update_entry(
        config_entry,
        options={"excluded_homes": [HOLIDAY_HOUSE]},
        pref_disable_polling=True,
    )
    await set_up(hass, config_entry)
    replies[SPEAKER][ALARMS] = ForToken(NEW_TOKEN, SUPPORTED[ALARMS])
    home_graph.return_value = graph(holiday_house())

    await refresh_devices(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert home_graph.await_count == 2
    assert not runtime(config_entry).client.google_devices_fetched
    assert await shown_repair(hass, issue_registry) == "homes_deselected"

    home_graph.side_effect = HomegraphError(grpc.StatusCode.UNAVAILABLE, "Unavailable")
    await update_account(hass, config_entry)

    assert home_graph.await_count == 3
    assert await shown_repair(hass, issue_registry) == "homes_deselected"


async def test_ignored_repair_stays_ignored_until_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Keep an ignored repair ignored when it shows again, also when the account then has no home and after a restart.

    Unloading the integration removes it, so after a reload it shows again, not
    ignored, if no home's devices are added then either.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    home_graph.return_value = graph(holiday_house())
    await set_up(hass, config_entry)
    ir.async_ignore_issue(hass, DOMAIN, ISSUE_NO_ADDED_HOME, True)

    await fetch_list(hass, config_entry, clock, 1)
    home_graph.return_value = graph()
    await fetch_list(hass, config_entry, clock, 2)

    assert await shown_repair(hass, issue_registry) == "no_home"
    issue = repair(issue_registry)
    assert issue is not None and issue.dismissed_version is not None

    # The registry's part of a restart: Home Assistant saves it, and loads it again
    # before setup, which doesn't unload the integration
    freezer.tick(timedelta(seconds=SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await issue_registry.async_load()
    issue = repair(issue_registry)
    assert issue is not None and not issue.active
    await fetch_list(hass, config_entry, clock, 3)

    assert await shown_repair(hass, issue_registry) == "no_home"
    issue = repair(issue_registry)
    assert issue is not None and issue.dismissed_version is not None

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await shown_repair(hass, issue_registry) == "no_home"
    issue = repair(issue_registry)
    assert issue is not None and issue.dismissed_version is None

    assert await hass.config_entries.async_unload(config_entry.entry_id)

    assert repair(issue_registry) is None


async def test_failed_start_removes_ignored_repair(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Remove the repair when setup fails, so it shows again, not ignored, once setup works.

    The repair is ignored from before Home Assistant started, which doesn't unload the
    integration. Setup then can't reach Google.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_NO_ADDED_HOME,
        config_entry_id=config_entry.entry_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="homes_deselected",
    )
    ir.async_ignore_issue(hass, DOMAIN, ISSUE_NO_ADDED_HOME, True)
    home_graph.side_effect = ClientConnectionError()

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert repair(issue_registry) is None

    home_graph.side_effect = None
    home_graph.return_value = graph(holiday_house())
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await shown_repair(hass, issue_registry) == "homes_deselected"
    issue = repair(issue_registry)
    assert issue is not None and issue.dismissed_version is None


@pytest.mark.parametrize(
    ("stale", "current", "shown"),
    [
        # The old fetch would show the repair that the new setup removed
        pytest.param(
            graph(holiday_house()),
            graph(at_home(), holiday_house()),
            False,
            id="no-stale-show",
        ),
        # The old fetch would remove the repair that the new setup showed
        pytest.param(
            graph(at_home(), holiday_house()),
            graph(holiday_house()),
            True,
            id="no-stale-removal",
        ),
    ],
)
async def test_fetch_answered_after_reload_leaves_repair(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    replies: Replies,
    issue_registry: ir.IssueRegistry,
    stale: HomeGraph,
    current: HomeGraph,
    shown: bool,
) -> None:
    """Leave the repair as the reloaded integration set it when an action's fetch from before the reload ends.

    After an update that doesn't fetch Google's list, as it isn't due, rebooting the
    kitchen speaker fetches it for a new token, as the speaker rejects its token.
    Google answers only after the integration reloaded and its setup got a home
    graph, and with the opposite one. Before the reload, the kitchen's home was added.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    await set_up(hass, config_entry)
    await update_account(hass, config_entry)
    replies[SPEAKER][REBOOT] = ForToken(NEW_TOKEN, (HTTPStatus.OK, {}))
    fetching, released = asyncio.Event(), asyncio.Event()

    async def answer(*_: object, **__: object) -> HomeGraph:
        """Answer the reboot's fetch once released, and the reloaded setup's at once."""
        if fetching.is_set():
            return current
        fetching.set()
        await released.wait()
        return stale

    home_graph.side_effect = answer
    reboot = asyncio.create_task(press_reboot(hass))
    await fetching.wait()
    # Not waiting for Home Assistant's tasks, which include the held reboot. Setup's
    # first update sets the repair before the reload returns.
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    assert (repair(issue_registry) is not None) is shown

    released.set()
    with pytest.raises(DeviceRequestFailed):
        await reboot
    await hass.async_block_till_done()

    assert home_graph.await_count == 3
    assert (repair(issue_registry) is not None) is shown
