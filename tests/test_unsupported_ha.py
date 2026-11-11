"""Tests for a Home Assistant older than the integration needs, running inside Home Assistant.

Home Assistant's version constants are patched to each release's values. Home
Assistant sets up the integration, runs its flows and keeps the repairs.
"""

from contextlib import AbstractContextManager
from datetime import timedelta
from importlib.metadata import version as package_version
import json
from pathlib import Path
from unittest.mock import Mock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.google_home.const import DOMAIN, MIN_HA_VERSION

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant import const as ha_const
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.registry import SAVE_DELAY
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.helpers.translation import async_get_translations

from .test_config_flow import SOURCES
from .test_init import MASTER_TOKEN
from .test_setup import set_up

# pylint: enable=wrong-import-order

HACS = Path(__file__).parents[1] / "hacs.json"
ISSUE = "unsupported_ha_version"
DOCS = (
    "https://ha-google-home.pages.dev/troubleshooting/"
    "#the-integration-doesnt-load-after-an-update"
)
UNSUPPORTED = ["2026.10.0", "2026.10.4", "2025.12.3"]
SUPPORTED = ["2026.11.0b0", "2026.11.0", "2026.12.1", "2027.1.0"]

# As an older version saved it, which migration would change: setup has always
# saved a master token, so it clears the app password
OLD_DATA = {
    "username": "test@example.com",
    "password": "app-password",
    "master_token": MASTER_TOKEN,
    "android_id": "android-id",
}
OPTIONS = {"update_interval": 30, "known_hosts": ["192.168.1.20"]}


def running(version: str) -> AbstractContextManager[object]:
    """Give Home Assistant's version constants the values that this release has."""
    major, minor = (int(part) for part in version.split(".")[:2])
    return patch.multiple(
        ha_const, MAJOR_VERSION=major, MINOR_VERSION=minor, __version__=version
    )


@pytest.fixture(name="old_entry")
def fixture_old_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return an entry that an older version saved, with options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="test@example.com",
        data=OLD_DATA,
        options=OPTIONS,
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    return entry


async def shown_text(hass: HomeAssistant, issue: ir.IssueEntry) -> dict[str, str]:
    """Return the repair's English title and description, with the placeholders filled."""
    text = await async_get_translations(hass, "en", "issues", [DOMAIN])
    prefix = f"component.{DOMAIN}.issues.{issue.translation_key}"
    return {
        part: text[f"{prefix}.{part}"].format(**(issue.translation_placeholders or {}))
        for part in ("title", "description")
    }


@pytest.mark.parametrize("version", UNSUPPORTED)
async def test_unsupported_ha_refuses_setup(
    hass: HomeAssistant,
    old_entry: MockConfigEntry,
    google: Mock,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
    version: str,
) -> None:
    """Set up nothing on an older Home Assistant, and say in Repairs which version is needed.

    The saved entry isn't migrated or changed, so an earlier release of the
    integration, or this one after Home Assistant is updated, finds it as it was.
    Neither Google nor the speakers are asked, and no action or entity is added.
    """
    with running(version):
        assert not await hass.config_entries.async_setup(old_entry.entry_id)
        await hass.async_block_till_done()

    assert old_entry.state is ConfigEntryState.NOT_LOADED
    assert (old_entry.minor_version, dict(old_entry.data), dict(old_entry.options)) == (
        1,
        OLD_DATA,
        OPTIONS,
    )
    assert google.call_count == aioclient_mock.call_count == 0
    assert hass.services.async_services_for_domain(DOMAIN) == {}
    assert er.async_entries_for_config_entry(entity_registry, old_entry.entry_id) == []

    issue = issue_registry.async_get_issue(DOMAIN, ISSUE)
    assert issue is not None and issue.active
    assert (issue.severity, issue.is_fixable, issue.translation_placeholders) == (
        ir.IssueSeverity.ERROR,
        False,
        {
            "current_version": version,
            "required_version": "2026.11",
            "docs_url": DOCS,
        },
    )
    text = await shown_text(hass, issue)
    assert text["title"] == "Google Home needs Home Assistant 2026.11 or later"
    assert f"this system runs {version}" in text["description"]
    assert DOCS in text["description"]
    assert f"needs Home Assistant 2026.11 or later, but this is {version}" in (
        caplog.text
    )


@pytest.mark.usefixtures("google", "replies")
@pytest.mark.parametrize("version", SUPPORTED)
async def test_supported_ha_sets_up(
    hass: HomeAssistant,
    old_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    version: str,
) -> None:
    """Set up an entry that an older version saved, without the repair, on a supported Home Assistant.

    The first beta of the oldest supported release already has what the integration
    needs.
    """
    with running(version):
        await set_up(hass, old_entry)

    assert old_entry.state is ConfigEntryState.LOADED
    assert old_entry.minor_version == 2
    assert issue_registry.async_get_issue(DOMAIN, ISSUE) is None


async def test_repair_gone_after_restart(
    hass: HomeAssistant,
    old_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Stop showing the repair after a restart, such as one that updates Home Assistant."""
    with running("2026.10.0"):
        assert not await hass.config_entries.async_setup(old_entry.entry_id)
        await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, ISSUE) is not None

    # The registry's part of a restart: Home Assistant saves it, and loads it again
    freezer.tick(timedelta(seconds=SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await issue_registry.async_load()

    issue = issue_registry.async_get_issue(DOMAIN, ISSUE)
    assert issue is not None and not issue.active


@pytest.mark.parametrize(("source", "data"), SOURCES)
@pytest.mark.parametrize("version", UNSUPPORTED)
async def test_unsupported_ha_refuses_first_setup(
    hass: HomeAssistant,
    source: str,
    data: ZeroconfServiceInfo | None,
    version: str,
) -> None:
    """Refuse to add the integration on an older Home Assistant, before asking how to sign in.

    A speaker that zeroconf finds isn't offered either.
    """
    with running(version):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": source}, data=data
        )

    assert (result["type"], result["reason"]) == (
        FlowResultType.ABORT,
        "unsupported-ha-version",
    )
    assert result["description_placeholders"] == {
        "current_version": version,
        "required_version": "2026.11",
        "docs_url": DOCS,
    }
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


@pytest.mark.parametrize(("source", "data"), SOURCES)
@pytest.mark.parametrize("version", SUPPORTED)
async def test_supported_ha_offers_first_setup(
    hass: HomeAssistant,
    source: str,
    data: ZeroconfServiceInfo | None,
    version: str,
) -> None:
    """Ask how to sign in on a supported Home Assistant, including its first beta."""
    with running(version):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": source}, data=data
        )

    assert (result["type"], result["step_id"]) == (FlowResultType.MENU, "user")


def test_minimum_is_the_declared_one() -> None:
    """Need the Home Assistant release that hacs.json and each release declare.

    Publishing a release sets the minimum in hacs.json to the Home Assistant version
    that the tests are pinned to, so raising that pin raises the minimum too.
    """
    declared = json.loads(HACS.read_text())["homeassistant"]
    pinned = package_version("homeassistant")

    assert [version.split(".")[:2] for version in (declared, pinned)] == [
        [str(part) for part in MIN_HA_VERSION]
    ] * 2
