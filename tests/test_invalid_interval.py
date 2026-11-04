"""Tests for the repair shown while the saved update interval is below 1 second.

Earlier versions saved one, which the integration replaces with the default 15
seconds. The repair's fix saves the default, or turns off polling for those who used
0 to stop the regular checks. Setup, reloads, the options form and the issue registry
run through Home Assistant.
"""

from datetime import timedelta
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.google_home.const import (
    CONF_BLUETOOTH_TRACKING,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    ISSUE_INVALID_INTERVAL,
    ISSUE_POLLING_DISABLED,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components.repairs import RepairsFlowResult, repairs_flow_manager
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from script.check_translations import placeholders

from .test_setup import set_up

# pylint: enable=wrong-import-order

DOCS_URL = "https://ha-google-home.pages.dev/configuration/#change-the-update-interval"
INTEGRATION_URL = "/config/integrations/integration/google_home"
POLLING_OFF_KEY = "invalid_update_interval_polling_off"


def repair(issue_registry: ir.IssueRegistry) -> ir.IssueEntry | None:
    """Return the repair about the saved update interval, if there is one."""
    return issue_registry.async_get_issue(DOMAIN, ISSUE_INVALID_INTERVAL)


async def open_fix(hass: HomeAssistant) -> RepairsFlowResult:
    """Open the repair's fix, as selecting it in Repairs does."""
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return await manager.async_init(
        DOMAIN, context={"issue_id": ISSUE_INVALID_INTERVAL}
    )


async def choose(
    hass: HomeAssistant, result: RepairsFlowResult, choice: str
) -> RepairsFlowResult:
    """Choose an option in the fix's menu, and wait for what it started."""
    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_configure(result["flow_id"], {"next_step_id": choice})
    await hass.async_block_till_done()
    return result


async def set_up_with(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    interval: int,
    *,
    polling_off: bool = False,
) -> None:
    """Set up the entry with the update interval saved by an earlier version.

    Another option shows that the fix keeps the rest of the options.
    """
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_UPDATE_INTERVAL: interval, CONF_BLUETOOTH_TRACKING: False},
        pref_disable_polling=polling_off,
    )
    # Not set_up(), as setup may fail
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("replies")
@pytest.mark.parametrize("interval", [0, -5])
@pytest.mark.parametrize(
    ("error", "entry_state"),
    [(None, ConfigEntryState.LOADED), (RuntimeError(), ConfigEntryState.SETUP_RETRY)],
    ids=["loaded", "setup retry"],
)
async def test_repair_for_interval_below_one_second(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
    interval: int,
    error: Exception | None,
    entry_state: ConfigEntryState,
) -> None:
    """Show a warning for the entry, whose fix names the saved interval.

    Also while setup is retried, as the saved interval stays meanwhile. Opening the
    fix changes nothing until the user chooses.
    """
    google.side_effect = error
    await set_up_with(hass, config_entry, interval)

    assert config_entry.state is entry_state
    issue = repair(issue_registry)
    assert issue is not None
    assert (
        issue.is_fixable,
        issue.severity,
        issue.config_entry_id,
        issue.translation_key,
    ) == (True, ir.IssueSeverity.WARNING, config_entry.entry_id, ISSUE_INVALID_INTERVAL)
    result = await open_fix(hass)
    assert (result["type"], result["step_id"], result.get("menu_options")) == (
        FlowResultType.MENU,
        "init",
        ["use_default", "turn_off_polling"],
    )
    assert result.get("description_placeholders") == {
        "interval": str(interval),
        "docs_url": DOCS_URL,
        "integration_url": INTEGRATION_URL,
    }
    assert config_entry.options[CONF_UPDATE_INTERVAL] == interval
    assert not config_entry.pref_disable_polling


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("options", [{}, {CONF_UPDATE_INTERVAL: 1}])
async def test_no_repair_for_valid_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    options: dict[str, int],
) -> None:
    """Show no repair for the default interval, or for 1 second, the shortest."""
    hass.config_entries.async_update_entry(config_entry, options=options)
    await set_up(hass, config_entry)

    assert repair(issue_registry) is None


async def test_repair_text(hass: HomeAssistant) -> None:
    """Name the saved interval and link to the docs and the integration in each text.

    While polling is off, the repair has its own text. Each menu option's text is
    checked as the fix shows it.
    """
    text = await async_get_translations(hass, "en", "issues", [DOMAIN])

    for key in (ISSUE_INVALID_INTERVAL, POLLING_OFF_KEY):
        prefix = f"component.{DOMAIN}.issues.{key}"
        step = f"{prefix}.fix_flow.step.init"
        assert placeholders(text[f"{prefix}.title"]) == set()
        assert placeholders(text[f"{step}.title"]) == set()
        assert placeholders(text[f"{step}.description"]) == {
            "interval",
            "docs_url",
            "integration_url",
        }


@pytest.mark.usefixtures("google", "replies")
async def test_repair_while_polling_off(
    hass: HomeAssistant, config_entry: MockConfigEntry, issue_registry: ir.IssueRegistry
) -> None:
    """Say when the default applies, and offer only to save it, as polling is off.

    Turning polling on reloads the entry, which changes the text and the choices.
    """
    await set_up_with(hass, config_entry, 0, polling_off=True)

    issue = repair(issue_registry)
    assert issue is not None and issue.translation_key == POLLING_OFF_KEY
    result = await open_fix(hass)
    assert (result["type"], result.get("menu_options")) == (
        FlowResultType.MENU,
        ["use_default"],
    )
    assert result.get("description_placeholders") == {
        "interval": "0",
        "docs_url": DOCS_URL,
        "integration_url": INTEGRATION_URL,
    }

    hass.config_entries.async_update_entry(config_entry, pref_disable_polling=False)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    issue = repair(issue_registry)
    assert issue is not None and issue.translation_key == ISSUE_INVALID_INTERVAL
    result = await open_fix(hass)
    assert result.get("menu_options") == ["use_default", "turn_off_polling"]


@pytest.mark.usefixtures("replies")
async def test_menu_follows_text_while_setup_retried(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
) -> None:
    """Keep the polling-off text and its menu if polling is turned on while setup fails.

    The entry isn't loaded, so Home Assistant doesn't reload it, and the text that
    setup chose stays until setup runs again. The menu matches it.
    """
    google.side_effect = RuntimeError()
    await set_up_with(hass, config_entry, 0, polling_off=True)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    hass.config_entries.async_update_entry(config_entry, pref_disable_polling=False)
    await hass.async_block_till_done()

    issue = repair(issue_registry)
    assert issue is not None and issue.translation_key == POLLING_OFF_KEY
    result = await open_fix(hass)
    assert result.get("menu_options") == ["use_default"]


@pytest.mark.usefixtures("replies")
@pytest.mark.parametrize(
    "polling_off", [False, True], ids=["polling on", "polling off"]
)
async def test_use_default(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
    polling_off: bool,
) -> None:
    """Save 15 seconds and keep the other options, without loading the entry again.

    Home Assistant removes the repair. Polling stays as it was, and so does its own
    repair.
    """
    await set_up_with(hass, config_entry, 0, polling_off=polling_off)
    polling_repair = issue_registry.async_get_issue(DOMAIN, ISSUE_POLLING_DISABLED)

    result = await choose(hass, await open_fix(hass), "use_default")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_UPDATE_INTERVAL: 15,
        CONF_BLUETOOTH_TRACKING: False,
    }
    assert config_entry.pref_disable_polling is polling_off
    assert repair(issue_registry) is None
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_POLLING_DISABLED) == (
        polling_repair
    )
    assert (polling_repair is not None) is polling_off
    assert config_entry.state is ConfigEntryState.LOADED
    assert google.call_count == 1


@pytest.mark.usefixtures("replies")
async def test_turn_off_polling(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
) -> None:
    """Save 15 seconds, turn polling off and load the entry again.

    The user chose polling off, so its repair is there but hidden, as if they kept
    polling off in it, and stays hidden after the reload.
    """
    await set_up_with(hass, config_entry, 0)

    result = await choose(hass, await open_fix(hass), "turn_off_polling")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_UPDATE_INTERVAL: 15,
        CONF_BLUETOOTH_TRACKING: False,
    }
    assert config_entry.pref_disable_polling
    assert config_entry.state is ConfigEntryState.LOADED
    # Loading it again fetched Google's list
    assert google.call_count == 2
    assert repair(issue_registry) is None
    polling_repair = issue_registry.async_get_issue(DOMAIN, ISSUE_POLLING_DISABLED)
    assert polling_repair is not None and polling_repair.dismissed_version is not None


@pytest.mark.usefixtures("replies")
async def test_options_change_shows_and_removes_repair(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
) -> None:
    """Show the repair once the options change to 0, and remove it once the form fixes it.

    The form refuses 0, but the options can change without it. The interval applies
    without loading the entry again, and so does the repair.
    """
    await set_up(hass, config_entry)

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 0}
    )
    await hass.async_block_till_done()
    assert repair(issue_registry) is not None

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_UPDATE_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_UPDATE_INTERVAL] == 30
    assert repair(issue_registry) is None
    assert google.call_count == 1


@pytest.mark.usefixtures("replies")
async def test_ignored_repair_kept_over_setup_retry_and_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Keep one repair, still hidden, when setup is retried and the entry reloads.

    A failed setup unloads what it started, and a reload unloads the entry, but the
    saved interval stays, so the repair does too.
    """
    google.side_effect = RuntimeError()
    await set_up_with(hass, config_entry, 0)
    states = [config_entry.state]
    ir.async_ignore_issue(hass, DOMAIN, ISSUE_INVALID_INTERVAL, True)

    google.side_effect = None
    # Home Assistant retries setup on its own
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    states.append(config_entry.state)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert states == [ConfigEntryState.SETUP_RETRY, ConfigEntryState.LOADED]
    assert google.call_count == 3
    assert [
        (issue.issue_id, issue.dismissed_version is not None)
        for issue in issue_registry.issues.values()
        if issue.domain == DOMAIN
    ] == [(ISSUE_INVALID_INTERVAL, True)]


@pytest.mark.usefixtures("google", "replies")
async def test_repair_of_disabled_and_deleted_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, issue_registry: ir.IssueRegistry
) -> None:
    """Keep the repair, hidden by Home Assistant, while the entry is disabled.

    Deleting the entry deletes its repair.
    """
    await set_up_with(hass, config_entry, 0)

    assert await hass.config_entries.async_set_disabled_by(
        config_entry.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    issue = repair(issue_registry)
    assert issue is not None and issue_registry.async_is_hidden(issue)

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert repair(issue_registry) is None


@pytest.mark.usefixtures("google", "replies")
async def test_fix_keeps_interval_saved_meanwhile(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Keep an interval that the options saved while the fix was open."""
    await set_up_with(hass, config_entry, 0)
    result = await open_fix(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    result = await choose(hass, result, "use_default")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_UPDATE_INTERVAL: 30}


@pytest.mark.usefixtures("replies")
async def test_fix_finishes_once_options_corrected_while_setup_retried(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    google: Mock,
) -> None:
    """Finish the fix straight away for an interval corrected before setup ran again.

    While setup is retried, changed options don't apply until it runs again, so the
    repair stays until then. Home Assistant removes it when the fix finishes.
    """
    google.side_effect = RuntimeError()
    await set_up_with(hass, config_entry, 0)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_UPDATE_INTERVAL: 30}
    )
    await hass.async_block_till_done()
    assert repair(issue_registry) is not None

    result = await open_fix(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_UPDATE_INTERVAL: 30}
    assert repair(issue_registry) is None


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("choice", ["use_default", "turn_off_polling"])
async def test_fix_finishes_once_entry_deleted(
    hass: HomeAssistant, config_entry: MockConfigEntry, choice: str
) -> None:
    """Finish the fix without changes if the entry was deleted while it was open."""
    await set_up_with(hass, config_entry, 0)
    result = await open_fix(hass)
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await choose(hass, result, choice)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.config_entries.async_entries(DOMAIN) == []
