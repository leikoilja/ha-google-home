"""Tests for choosing the Google homes whose devices are added, running inside Home Assistant.

The kitchen speaker is at home and the bedroom speaker in the holiday house. As in
test_removed_devices, glocaltokens itself makes the device list from Google's home
graph, and the options flow and the reload it causes run through Home Assistant.
"""

from collections.abc import Iterator
from http import HTTPStatus
import logging
from unittest.mock import MagicMock, Mock, patch

from ghome_foyer_api.api_pb2 import HomeGraph  # pylint: disable=no-name-in-module
from glocaltokens.exceptions import HomegraphError
from glocaltokens.scanner import NetworkDevice
import grpc  # type: ignore[import-untyped]
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.google_home.const import DOMAIN

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.config_entries import SOURCE_USER, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    Replies,
)
from .test_coordinators import (
    BEDROOM_ALARMS,
    BEDROOM_DEVICE,
    KITCHEN_ALARMS,
    KITCHEN_DEVICE,
    asked,
    asked_by,
    runtime,
    update_account,
)
from .test_diagnostics import TV, TV_CLOUD_ID, TV_NAME
from .test_missing_devices import MASTER_TOKEN, logged
from .test_removed_devices import (
    BEDROOM_CLOUD_ID,
    KITCHEN_IN_HOME_GRAPH,
    bedroom_device,
    entity_ids,
    fetch_list,
    in_home_graph,
)
from .test_setup import set_up, state
from .test_unsupported_devices import INFO, SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order

HOME = "home-id"
HOLIDAY_HOUSE = "holiday-house-id"
# A home that the account joins later, with no devices unless a test adds some
NEW_HOME = "new-home-id"
BEDROOM_IN_HOME_GRAPH = in_home_graph(BEDROOM_ID, BEDROOM_CLOUD_ID, "Bedroom speaker")
ALARM_SHOWN = "2023-11-14T14:13:20-08:00"


def home(home_id: str, name: str, *devices: HomeGraph.Device) -> HomeGraph.Home:
    """Return a home of Google's home graph."""
    return HomeGraph.Home(id=home_id, display_name=name, devices=devices)


def at_home() -> HomeGraph.Home:
    """Return the home with the kitchen speaker."""
    return home(HOME, "Home", KITCHEN_IN_HOME_GRAPH)


def holiday_house(*devices: HomeGraph.Device) -> HomeGraph.Home:
    """Return the holiday house, with the bedroom speaker unless other devices are given."""
    return home(HOLIDAY_HOUSE, "Holiday house", *(devices or [BEDROOM_IN_HOME_GRAPH]))


def graph(*homes: HomeGraph.Home) -> HomeGraph:
    """Return a home graph with these homes."""
    return HomeGraph(homes=homes)


@pytest.fixture(name="home_graph")
def fixture_home_graph(
    mock_async_zeroconf: MagicMock,  # pylint: disable=unused-argument
    replies: Replies,
) -> Iterator[Mock]:
    """Fake Google's home graph with both homes, and mDNS, which finds both speakers."""
    replies[BEDROOM] = dict(SUPPORTED)
    with (
        patch(
            "glocaltokens.client.GLocalAuthenticationTokens.get_home_graph",
            autospec=True,
            return_value=graph(at_home(), holiday_house()),
        ) as home_graph,
        patch(
            "glocaltokens.client.discover_devices",
            return_value=[
                NetworkDevice(
                    SPEAKER_NAME, SPEAKER, 8009, "Nest Audio", SPEAKER_CLOUD_ID
                ),
                NetworkDevice(
                    "Bedroom speaker", BEDROOM, 8009, "Nest Audio", BEDROOM_CLOUD_ID
                ),
            ],
        ),
        patch("custom_components.google_home.mdns.AsyncServiceBrowser"),
    ):
        yield home_graph


@pytest.fixture(name="sign_in")
def fixture_sign_in() -> Iterator[None]:
    """Fake Google giving an access token for any master token, without an email address."""
    with (
        patch("glocaltokens.client.perform_oauth", return_value={"Auth": "access"}),
        patch(
            "glocaltokens.client.GLocalAuthenticationTokens.get_email",
            autospec=True,
            return_value=None,
        ),
    ):
        yield


async def open_options(hass: HomeAssistant, entry: MockConfigEntry) -> ConfigFlowResult:
    """Open the options."""
    return await hass.config_entries.options.async_init(entry.entry_id)


async def save_options(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict[str, object]
) -> ConfigFlowResult:
    """Submit the options form, and wait for the reload that it may cause."""
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    return result


async def choose_homes(
    hass: HomeAssistant, entry: MockConfigEntry, homes: list[str]
) -> ConfigFlowResult:
    """Choose the homes whose devices are added in the options."""
    return await save_options(hass, await open_options(hass, entry), {"homes": homes})


def offered(result: ConfigFlowResult) -> dict[str, object] | None:
    """Return the homes that a form offers, and which are selected, if it has the field."""
    schema = result["data_schema"]
    assert schema is not None
    fields = {str(key): key for key in schema.schema}
    if "homes" not in fields:
        return None
    selector = schema.schema[fields["homes"]]
    return {
        "labels": [option["label"] for option in selector.config["options"]],
        "selected": schema({})["homes"],
    }


@pytest.mark.usefixtures("home_graph", "sign_in")
async def test_add_integration_with_chosen_homes(hass: HomeAssistant) -> None:
    """Offer the homes by name after signing in, all selected, and add the chosen home's devices.

    Choosing none is refused. The homes left out are saved, not those chosen, so a
    home that the account joins later has its devices added.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "master_token"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"master_token": MASTER_TOKEN}
    )

    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "homes")
    assert offered(result) == {
        "labels": ["Holiday house", "Home"],
        "selected": [HOME, HOLIDAY_HOUSE],
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"homes": []}
    )

    assert result["errors"] == {"homes": "no-home-selected"}
    assert hass.config_entries.async_entries(DOMAIN) == []

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"homes": [HOME]}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.options == {"excluded_homes": [HOLIDAY_HOUSE]}
    assert state(hass, KITCHEN_ALARMS) == ALARM_SHOWN
    assert hass.states.get(BEDROOM_ALARMS) is None


@pytest.mark.usefixtures("home_graph")
async def test_deselected_home_removed_and_added_back(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Remove a deselected home's speaker with its entities as the integration reloads, and stop asking it.

    Selected again, it comes back with the area and name the user gave it, as Home
    Assistant keeps the settings of the entry's deleted devices.
    """
    await set_up(hass, config_entry)
    bedroom = bedroom_device(device_registry, config_entry)
    assert bedroom is not None
    upstairs = area_registry.async_create("Upstairs")
    device_registry.async_update_device(
        bedroom.id, area_id=upstairs.id, name_by_user="Guest room speaker"
    )
    result = await open_options(hass, config_entry)
    assert offered(result) == {
        "labels": ["Holiday house", "Home"],
        "selected": [HOME, HOLIDAY_HOUSE],
    }
    asked(aioclient_mock)

    result = await save_options(hass, result, {"homes": [HOME]})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "update_interval": 15,
        "known_hosts": [],
        "excluded_homes": [HOLIDAY_HOUSE],
    }
    assert bedroom_device(device_registry, config_entry) is None
    assert BEDROOM_ALARMS not in entity_ids(entity_registry, config_entry)
    assert state(hass, KITCHEN_ALARMS) == ALARM_SHOWN
    assert asked_by(asked(aioclient_mock), BEDROOM) == []
    assert (
        "INFO",
        "Removed Guest room speaker, which is in a home whose devices aren't added",
    ) in logged(caplog)

    await choose_homes(hass, config_entry, [HOME, HOLIDAY_HOUSE])

    assert config_entry.options == {"update_interval": 15, "known_hosts": []}
    restored = bedroom_device(device_registry, config_entry)
    assert restored is not None
    assert (restored.id, restored.area_id, restored.name_by_user) == (
        bedroom.id,
        upstairs.id,
        "Guest room speaker",
    )
    assert state(hass, BEDROOM_ALARMS) == ALARM_SHOWN


@pytest.mark.parametrize(
    "unusable",
    [
        pytest.param({"token": ""}, id="no-local-token"),
        pytest.param({"token": "x" * 20}, id="token-of-another-format"),
        pytest.param({"name": ""}, id="no-name"),
    ],
)
async def test_deselected_home_speaker_glocaltokens_leaves_out_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    device_registry: dr.DeviceRegistry,
    unusable: dict[str, str],
) -> None:
    """Remove a deselected home's speaker even when glocaltokens leaves it out of the list.

    The home graph still has it in that home, so it doesn't wait for two lists
    without it, which would never come.
    """
    await set_up(hass, config_entry)
    bedroom = {"name": "Bedroom speaker"} | unusable
    home_graph.return_value = graph(
        at_home(),
        holiday_house(in_home_graph(BEDROOM_ID, BEDROOM_CLOUD_ID, **bedroom)),
    )

    await choose_homes(hass, config_entry, [HOME])

    assert bedroom_device(device_registry, config_entry) is None
    assert state(hass, KITCHEN_ALARMS) == ALARM_SHOWN


async def test_deselected_home_removed_once_google_answers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Remove nothing while Google doesn't give the home graph after deselecting a home.

    Once it does, a minute later, the deselected home's speaker is removed and the
    other stays.
    """
    await set_up(hass, config_entry)
    home_graph.side_effect = HomegraphError(grpc.StatusCode.UNAVAILABLE, "Unavailable")

    await choose_homes(hass, config_entry, [HOME])

    assert bedroom_device(device_registry, config_entry) is not None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, SPEAKER_ID), config_entry.entry_id
        )
        is not None
    )

    home_graph.side_effect = None
    clock.return_value = 60
    await update_account(hass, config_entry)

    assert bedroom_device(device_registry, config_entry) is None
    assert state(hass, KITCHEN_ALARMS) == ALARM_SHOWN


async def test_home_without_id_added(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Add the devices of a home without an ID, which can't be excluded, when another home is."""
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    home_graph.return_value = graph(
        home("", "Home", KITCHEN_IN_HOME_GRAPH), holiday_house()
    )

    await set_up(hass, config_entry)

    assert state(hass, KITCHEN_ALARMS) == ALARM_SHOWN
    assert bedroom_device(device_registry, config_entry) is None


async def test_home_joined_later_added(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
) -> None:
    """Add the devices of a home that the account joins after other homes were excluded."""
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    home_graph.return_value = graph(at_home(), home(HOLIDAY_HOUSE, "Holiday house"))
    await set_up(hass, config_entry)
    assert hass.states.get(BEDROOM_ALARMS) is None

    home_graph.return_value = graph(
        at_home(),
        home(HOLIDAY_HOUSE, "Holiday house"),
        home(NEW_HOME, "New home", BEDROOM_IN_HOME_GRAPH),
    )
    await fetch_list(hass, config_entry, clock, 1)

    assert state(hass, BEDROOM_ALARMS) == ALARM_SHOWN


def home_attribute(hass: HomeAssistant, entity_id: str) -> object:
    """Return the home attribute of a device sensor."""
    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    return entity_state.attributes["home"]


@pytest.mark.usefixtures("home_graph")
async def test_device_sensors_show_their_home(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Show the name of each speaker's own home in its device sensor."""
    await set_up(hass, config_entry)

    assert home_attribute(hass, KITCHEN_DEVICE) == "Home"
    assert home_attribute(hass, BEDROOM_DEVICE) == "Holiday house"


async def test_device_sensor_home_without_name(
    hass: HomeAssistant, config_entry: MockConfigEntry, home_graph: Mock
) -> None:
    """Show no home name, rather than the home's ID, when Google gives the home none."""
    home_graph.return_value = graph(home(HOME, "", KITCHEN_IN_HOME_GRAPH))

    await set_up(hass, config_entry)

    assert home_attribute(hass, KITCHEN_DEVICE) is None


async def test_device_sensor_follows_renamed_home(
    hass: HomeAssistant, config_entry: MockConfigEntry, home_graph: Mock, clock: Mock
) -> None:
    """Show a home's new name at the speaker's update after Google's list is fetched again."""
    await set_up(hass, config_entry)
    home_graph.return_value = graph(
        home(HOME, "Main house", KITCHEN_IN_HOME_GRAPH), holiday_house()
    )

    await fetch_list(hass, config_entry, clock, 1)
    await runtime(config_entry).devices[SPEAKER_ID].async_refresh()

    assert home_attribute(hass, KITCHEN_DEVICE) == "Main house"


@pytest.mark.usefixtures("home_graph")
async def test_excluded_home_speaker_not_reported_missing(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Don't count or log an excluded home's speaker that mDNS finds as missing from Google's list.

    Google lists it; the user left its home out. A Cast device that no home has, such
    as a TV, still counts as missing in diagnostics and the log.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    await set_up(hass, config_entry)
    found_devices = runtime(config_entry).client.found_devices

    found_devices.async_device_found(BEDROOM_CLOUD_ID, "Bedroom speaker", BEDROOM)
    found_devices.async_device_found(TV_CLOUD_ID, TV_NAME, TV)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )
    assert diagnostics["mdns_reported_not_listed"] == 1
    assert [
        message for _, message in logged(caplog) if message.startswith("mDNS found")
    ] == [
        (
            f"mDNS found Bedroom speaker at {BEDROOM}, which is in a home whose"
            " devices aren't added"
        ),
        f"mDNS found {TV_NAME} at {TV}, which isn't in Google's device list",
    ]


async def test_known_host_of_excluded_home_not_added(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,  # pylint: disable=unused-argument
    replies: Replies,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Don't add an excluded home's speaker at a known host, though it's asked which device it is.

    mDNS finds neither speaker, so the known host is asked for the kitchen speaker.
    """
    replies[BEDROOM][INFO] = (
        HTTPStatus.OK,
        {"device_info": {"cloud_device_id": BEDROOM_CLOUD_ID}},
    )
    hass.config_entries.async_update_entry(
        config_entry,
        options={"known_hosts": [BEDROOM], "excluded_homes": [HOLIDAY_HOUSE]},
    )

    with patch("glocaltokens.client.discover_devices", return_value=[]):
        await set_up(hass, config_entry)

    assert asked_by(asked(aioclient_mock), BEDROOM) == [INFO]
    assert bedroom_device(device_registry, config_entry) is None


async def test_options_offer_excluded_home_alone(
    hass: HomeAssistant, config_entry: MockConfigEntry, home_graph: Mock, clock: Mock
) -> None:
    """Offer the one home left when it's excluded, so it can be added again.

    Other options can still be saved while it stays excluded.
    """
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    await set_up(hass, config_entry)
    # The account leaves the home whose devices were added
    home_graph.return_value = graph(holiday_house())
    await fetch_list(hass, config_entry, clock, 1)

    result = await open_options(hass, config_entry)
    assert offered(result) == {"labels": ["Holiday house"], "selected": []}
    result = await save_options(hass, result, {"update_interval": 30, "homes": []})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "update_interval": 30,
        "known_hosts": [],
        "excluded_homes": [HOLIDAY_HOUSE],
    }

    await choose_homes(hass, config_entry, [HOLIDAY_HOUSE])

    assert config_entry.options == {"update_interval": 30, "known_hosts": []}
    assert state(hass, BEDROOM_ALARMS) == ALARM_SHOWN


@pytest.mark.parametrize(
    ("homes", "shown"),
    [
        # Another home is offered, without the excluded one
        pytest.param(
            [at_home(), home(NEW_HOME, "New home")],
            {"labels": ["Home", "New home"], "selected": [HOME, NEW_HOME]},
            id="offered",
        ),
        # No choice: the form has no homes
        pytest.param([at_home()], None, id="not-offered"),
    ],
)
async def test_options_keep_excluded_home_google_leaves_out(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
    homes: list[HomeGraph.Home],
    shown: dict[str, object] | None,
) -> None:
    """Keep a home excluded while Google's home graph lacks it, when other options are saved."""
    hass.config_entries.async_update_entry(
        config_entry, options={"excluded_homes": [HOLIDAY_HOUSE]}
    )
    await set_up(hass, config_entry)
    home_graph.return_value = graph(*homes)
    await fetch_list(hass, config_entry, clock, 1)

    result = await open_options(hass, config_entry)
    assert offered(result) == shown
    homes_input = {"homes": [HOME, NEW_HOME]} if shown else {}
    await save_options(hass, result, {"update_interval": 30, **homes_input})

    assert config_entry.options == {
        "update_interval": 30,
        "known_hosts": [],
        "excluded_homes": [HOLIDAY_HOUSE],
    }


async def test_options_home_joined_while_form_open_added(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    home_graph: Mock,
    clock: Mock,
) -> None:
    """Don't exclude a home that the account joins while the options are open, as the form didn't offer it."""
    await set_up(hass, config_entry)
    result = await open_options(hass, config_entry)
    home_graph.return_value = graph(
        at_home(), holiday_house(), home(NEW_HOME, "New home")
    )
    await fetch_list(hass, config_entry, clock, 1)

    await save_options(hass, result, {"homes": [HOME, HOLIDAY_HOUSE]})

    assert config_entry.options == {"update_interval": 15, "known_hosts": []}


@pytest.mark.usefixtures("home_graph")
async def test_options_no_home_refused(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Refuse to deselect every home whose devices are added, showing the homes as the user left them."""
    await set_up(hass, config_entry)

    result = await choose_homes(hass, config_entry, [])

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"homes": "no-home-selected"}
    assert offered(result) == {"labels": ["Holiday house", "Home"], "selected": []}
    assert config_entry.options == {}
