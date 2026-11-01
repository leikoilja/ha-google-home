"""Tests for the sensors of each device's Wi-Fi network and signal strength.

They're disabled by default, so these tests enable them.
"""

from http import HTTPStatus
from unittest.mock import Mock

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.const import FIRMWARE_CHECK_INTERVAL

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import SPEAKER_ID, Replies
from .test_coordinators import runtime
from .test_setup import (
    WIFI_NETWORK_SENSOR,
    WIFI_SIGNAL_SENSOR,
    set_up,
    shown_icons,
    state,
)
from .test_unsupported_devices import NO_ALARMS, SPEAKER, UPDATE, Reply

# pylint: enable=wrong-import-order

NETWORK = "Invented home Wi-Fi"
OTHER_NETWORK = "Invented upstairs Wi-Fi"


def info(**wifi: object) -> Reply:
    """Return a device's info without params, with a few invented fields and these Wi-Fi fields."""
    return HTTPStatus.OK, {
        "name": "Speaker",
        "has_update": False,
        "uptime": 1234.5,
        **wifi,
    }


def shown(hass: HomeAssistant) -> tuple[str, str]:
    """Return the states of the speaker's Wi-Fi network and signal sensors."""
    return state(hass, WIFI_NETWORK_SENSOR), state(hass, WIFI_SIGNAL_SENSOR)


@pytest.mark.usefixtures("google", "entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param(
            info(ssid=NETWORK, signal_level=-52), (NETWORK, "-52"), id="speaker"
        ),
        # A display such as a Nest Hub gives its network, but no signal
        pytest.param(info(ssid=NETWORK), (NETWORK, STATE_UNKNOWN), id="display"),
        pytest.param(
            info(ssid=NETWORK, signal_level=-52.5), (NETWORK, "-52.5"), id="fraction"
        ),
        # Only a non-empty string is a network, and only a JSON number a signal
        pytest.param(
            info(ssid="", signal_level=True),
            (STATE_UNKNOWN, STATE_UNKNOWN),
            id="empty-and-true",
        ),
        pytest.param(
            info(ssid=5, signal_level="-52"),
            (STATE_UNKNOWN, STATE_UNKNOWN),
            id="wrong-types",
        ),
        pytest.param(HTTPStatus.NOT_FOUND, (STATE_UNKNOWN, STATE_UNKNOWN), id="404"),
    ],
)
async def test_wifi_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    reply: Reply,
    expected: tuple[str, str],
) -> None:
    """Show the network and signal strength that the speaker's info gives, else unknown."""
    replies[SPEAKER][UPDATE] = reply
    await set_up(hass, config_entry)
    assert shown(hass) == expected


@pytest.mark.usefixtures("google", "entity_registry_enabled_by_default")
async def test_wifi_sensors_follow_checks(
    hass: HomeAssistant, config_entry: MockConfigEntry, replies: Replies, clock: Mock
) -> None:
    """Change the Wi-Fi sensors at each check, keeping them when the speaker's info doesn't come.

    Info that leaves the fields out makes them unknown.
    """
    replies[SPEAKER][UPDATE] = info(ssid=NETWORK, signal_level=-52)
    await set_up(hass, config_entry)
    assert shown(hass) == (NETWORK, "-52")

    speaker = runtime(config_entry).devices[SPEAKER_ID]
    checks: list[tuple[Reply, tuple[str, str]]] = [
        (info(ssid=OTHER_NETWORK, signal_level=-71), (OTHER_NETWORK, "-71")),
        (HTTPStatus.NOT_FOUND, (OTHER_NETWORK, "-71")),
        (TimeoutError(), (OTHER_NETWORK, "-71")),
        (info(), (STATE_UNKNOWN, STATE_UNKNOWN)),
    ]
    for check, (reply, expected) in enumerate(checks, start=1):
        replies[SPEAKER][UPDATE] = reply
        clock.return_value = check * FIRMWARE_CHECK_INTERVAL
        await speaker.async_refresh()
        assert shown(hass) == expected, check


@pytest.mark.usefixtures("google", "entity_registry_enabled_by_default")
async def test_wifi_sensors_without_alarms(
    hass: HomeAssistant, config_entry: MockConfigEntry, replies: Replies
) -> None:
    """Add the Wi-Fi sensors to a speaker whose alarms don't answer, as its info does.

    Its alarms, timers and settings entities wait for an answer, but a device without
    them, such as a Chromecast Audio, has Wi-Fi too.
    """
    replies[SPEAKER] = {**NO_ALARMS, UPDATE: info(ssid=NETWORK, signal_level=-48)}
    await set_up(hass, config_entry)

    assert hass.states.get("sensor.kitchen_speaker_alarms") is None
    assert shown(hass) == (NETWORK, "-48")


@pytest.mark.usefixtures("google", "replies", "entity_registry_enabled_by_default")
async def test_wifi_icons(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Show a Wi-Fi icon for the network, and no icon of its own for the signal.

    The frontend shows its icons for signal strength.
    """
    await set_up(hass, config_entry)

    assert await shown_icons(
        hass, entity_registry, [WIFI_NETWORK_SENSOR, WIFI_SIGNAL_SENSOR]
    ) == {WIFI_NETWORK_SENSOR: "mdi:wifi", WIFI_SIGNAL_SENSOR: None}
