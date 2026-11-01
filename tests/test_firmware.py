"""Tests for showing each device's firmware version and whether an update is waiting."""

from http import HTTPStatus
from unittest.mock import Mock

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.binary_sensor import FirmwareUpdateBinarySensor
from custom_components.google_home.const import DOMAIN, FIRMWARE_CHECK_INTERVAL
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import WifiNetworkSensor, WifiSignalSensor

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import SPEAKER_ID, Replies
from .test_coordinators import EVERYTHING, FIRMWARE, coordinators, runtime
from .test_missing_devices import make_client
from .test_setup import UPDATE_SENSOR, set_up, state
from .test_unsupported_devices import (
    ALARMS,
    BUILD,
    INFO,
    NO_ALARMS,
    SPEAKER,
    SUPPORTED,
    UPDATE,
    Network,
    Reply,
    build_info,
    update_info,
)

# pylint: enable=wrong-import-order

# The speaker's firmware in SUPPORTED, and a newer one
SHOWN = "3.77.512345"
NEWER = build_info("3.78.523456", "523456")
# An answer of the right kind that says nothing about firmware
INFO_WITHOUT_FIRMWARE: Reply = (HTTPStatus.OK, {"name": "Speaker"})


@pytest.mark.parametrize(
    ("fields", "version"),
    [
        pytest.param(
            {"cast_build_revision": "3.77.512345", "system_build_number": "512345"},
            "3.77.512345",
            id="speaker",
        ),
        pytest.param(
            {
                "cast_build_revision": "3.79.234567",
                "system_build_number": "31.20260101.103.1234567",
            },
            "31.20260101.103.1234567",
            id="display",
        ),
        pytest.param({"cast_build_revision": "3.77.512345"}, "3.77.512345", id="cast"),
        pytest.param({"system_build_number": "512345"}, "512345", id="system"),
        pytest.param(
            {"cast_build_revision": "", "system_build_number": 512345},
            None,
            id="not-versions",
        ),
        pytest.param({}, None, id="none"),
    ],
)
def test_firmware_version(fields: dict[str, object], version: str | None) -> None:
    """Give the version in the form Google publishes: a display's system version, else the Cast version."""
    device = GoogleHomeDevice("kitchen", "Kitchen speaker", "token")
    device.build_info = fields
    assert device.sw_version == version


def shown_firmware(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry
) -> str | None:
    """Return the firmware version that the speaker's device page shows."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SPEAKER_ID), entry.entry_id
    )
    assert device is not None
    return device.sw_version


@pytest.mark.usefixtures("google")
async def test_device_page_shows_firmware(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    clock: Mock,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Show the speaker's firmware version from setup, and a new one at the next check.

    Home Assistant reads it from the entities only when it adds them. A check that
    gets no version keeps the one shown. Looking the device up in the registry uses no
    API that Home Assistant has deprecated.
    """
    await set_up(hass, config_entry)
    assert shown_firmware(device_registry, config_entry) == SHOWN

    speaker = runtime(config_entry).devices[SPEAKER_ID]
    replies[SPEAKER][BUILD] = NEWER
    clock.return_value = FIRMWARE_CHECK_INTERVAL
    await speaker.async_refresh()
    assert shown_firmware(device_registry, config_entry) == "3.78.523456"

    # An answer that isn't its info, and no answer, keep what the speaker said, and
    # info without build info makes its version unknown
    checks: list[tuple[Reply, str | None]] = [
        (HTTPStatus.NOT_FOUND, "3.78.523456"),
        (TimeoutError(), "3.78.523456"),
        (INFO_WITHOUT_FIRMWARE, None),
    ]
    for check, (reply, known) in enumerate(checks, start=2):
        replies[SPEAKER][BUILD] = reply
        clock.return_value = check * FIRMWARE_CHECK_INTERVAL
        await speaker.async_refresh()
        assert speaker.data is not None
        assert speaker.data.sw_version == known
        assert shown_firmware(device_registry, config_entry) == "3.78.523456"

    # Home Assistant warns once about each place where a custom integration calls an
    # API that it deprecated, such as the registry's async_get_device
    assert not [
        record.getMessage()
        for record in caplog.records
        if record.name == "homeassistant.helpers.frame"
        and "integration 'google_home'" in record.getMessage()
    ]


@pytest.mark.usefixtures("google")
async def test_device_page_keeps_firmware_while_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Keep the version that the device page showed before a restart while the speaker's is unknown.

    Here its build info doesn't answer at setup. The entities' device info then
    leaves the version out, as Home Assistant would clear it for None.
    """
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, SPEAKER_ID)},
        sw_version="3.76.501234",
    )
    replies[SPEAKER][BUILD] = TimeoutError()
    await set_up(hass, config_entry)

    assert shown_firmware(device_registry, config_entry) == "3.76.501234"


@pytest.mark.usefixtures("google")
@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        pytest.param(update_info(True), STATE_ON, id="true"),
        pytest.param(update_info(False), STATE_OFF, id="false"),
        # Only the JSON true or false is a clear answer
        pytest.param(update_info("true"), STATE_UNKNOWN, id="string"),
        pytest.param(update_info(1), STATE_UNKNOWN, id="number"),
        pytest.param(INFO_WITHOUT_FIRMWARE, STATE_UNKNOWN, id="missing"),
        pytest.param(HTTPStatus.NOT_FOUND, STATE_UNKNOWN, id="404"),
    ],
)
async def test_update_sensor(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    reply: Reply,
    shown: str,
) -> None:
    """Show whether the speaker's info says that a firmware update is waiting."""
    replies[SPEAKER][UPDATE] = reply
    await set_up(hass, config_entry)
    assert state(hass, UPDATE_SENSOR) == shown


@pytest.mark.usefixtures("google")
async def test_update_sensor_follows_checks(
    hass: HomeAssistant, config_entry: MockConfigEntry, replies: Replies, clock: Mock
) -> None:
    """Change the update sensor at each check, keeping it when the speaker's info doesn't come.

    Info that leaves the flag out makes it unknown, rather than keep an update that
    may have been installed.
    """
    replies[SPEAKER][UPDATE] = update_info(True)
    await set_up(hass, config_entry)
    assert state(hass, UPDATE_SENSOR) == STATE_ON

    speaker = runtime(config_entry).devices[SPEAKER_ID]
    checks: list[tuple[Reply, str]] = [
        (update_info(False), STATE_OFF),
        (HTTPStatus.NOT_FOUND, STATE_OFF),
        (TimeoutError(), STATE_OFF),
        (INFO_WITHOUT_FIRMWARE, STATE_UNKNOWN),
    ]
    for check, (reply, shown) in enumerate(checks, start=1):
        replies[SPEAKER][UPDATE] = reply
        clock.return_value = check * FIRMWARE_CHECK_INTERVAL
        await speaker.async_refresh()
        assert state(hass, UPDATE_SENSOR) == shown


@pytest.mark.usefixtures("google")
async def test_update_sensor_without_alarms(
    hass: HomeAssistant, config_entry: MockConfigEntry, replies: Replies
) -> None:
    """Add the update sensor to a speaker whose alarms don't answer, as its info does.

    Its alarms, timers and settings entities wait for an answer, but a device without
    them, such as a Chromecast Audio, has firmware too.
    """
    replies[SPEAKER] = dict(NO_ALARMS)
    replies[SPEAKER][UPDATE] = update_info(True)
    await set_up(hass, config_entry)

    assert hass.states.get("sensor.kitchen_speaker_alarms") is None
    assert state(hass, UPDATE_SENSOR) == STATE_ON


@pytest.mark.parametrize(
    "sensor_class", [FirmwareUpdateBinarySensor, WifiNetworkSensor, WifiSignalSensor]
)
@pytest.mark.parametrize(
    ("ip_address", "listed", "available"),
    [("10.0.0.2", True, True), (None, True, False), ("10.0.0.2", False, False)],
)
def test_update_and_wifi_sensors_available(
    sensor_class: type[GoogleHomeBaseEntity],
    ip_address: str | None,
    listed: bool,
    available: bool,
) -> None:
    """Grey out the update and Wi-Fi sensors of a device that isn't found or has no IP address, as its device sensor."""
    device = GoogleHomeDevice("kitchen", "Kitchen speaker", "token", ip_address)
    coordinator = Mock(data=device if listed else None, last_update_success=True)
    sensor = sensor_class(coordinator, Mock(), "kitchen", "Kitchen speaker", None)

    assert sensor.available is available


def network_with_speaker(
    hass: HomeAssistant, entry: MockConfigEntry, replies: dict[str, Reply]
) -> tuple[Network, GoogleHomeDevice]:
    """Return the network with a speaker that answers so, and the speaker, whose updates the test runs."""
    network = Network()
    network.replies[SPEAKER] = dict(replies)
    client, _ = make_client(SPEAKER, session=network.session)
    coordinators(hass, entry, client)
    [device] = client.google_devices
    return network, device


async def update(entry: MockConfigEntry, clock: Mock, seconds: int) -> None:
    """Run the speaker's update at this time, after the account's, which adds its coordinator."""
    clock.return_value = seconds
    data = runtime(entry)
    if not data.devices:
        await data.account.async_refresh()
    await data.devices["device0"].async_refresh()


async def test_firmware_checked_every_20_minutes(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: Mock
) -> None:
    """Ask the speaker for its firmware at its first update, then 20 minutes after each check started.

    Firmware changes rarely, so the other updates don't ask.
    """
    network, _ = network_with_speaker(hass, config_entry, SUPPORTED)
    for seconds, asked in [
        (0, [*EVERYTHING, *FIRMWARE]),
        (15, EVERYTHING),
        (FIRMWARE_CHECK_INTERVAL - 1, EVERYTHING),
        (FIRMWARE_CHECK_INTERVAL, [*EVERYTHING, *FIRMWARE]),
        (2 * FIRMWARE_CHECK_INTERVAL - 1, EVERYTHING),
    ]:
        await update(config_entry, clock, seconds)
        assert network.asked(SPEAKER) == asked, seconds


async def test_firmware_not_asked_when_speaker_does_not_answer(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: Mock
) -> None:
    """Don't ask a speaker that didn't answer at this update for its firmware, nor for more after no answer.

    A speaker that stalls gets no more requests. A check that fails waits for the
    next one, and a speaker that doesn't answer for its build info isn't asked for
    whether an update is waiting.
    """
    network, device = network_with_speaker(
        hass, config_entry, {**SUPPORTED, ALARMS: TimeoutError(), INFO: TimeoutError()}
    )
    await update(config_entry, clock, 0)
    assert network.asked(SPEAKER) == [ALARMS, INFO]

    network.replies[SPEAKER] = {**SUPPORTED, BUILD: TimeoutError()}
    await update(config_entry, clock, 15)
    assert network.asked(SPEAKER) == [*EVERYTHING, BUILD]

    network.replies[SPEAKER] = dict(SUPPORTED)
    await update(config_entry, clock, 15 + FIRMWARE_CHECK_INTERVAL - 1)
    assert network.asked(SPEAKER) == EVERYTHING
    assert device.sw_version is None

    await update(config_entry, clock, 15 + FIRMWARE_CHECK_INTERVAL)
    assert network.asked(SPEAKER) == [*EVERYTHING, *FIRMWARE]
    assert device.sw_version == SHOWN


async def test_firmware_of_device_without_alarms(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: Mock
) -> None:
    """Ask a device without alarms for its firmware every 20 minutes, and still not for alarms or settings.

    At each update it's asked only for its info, which shows whether it answers.
    """
    network, device = network_with_speaker(hass, config_entry, NO_ALARMS)
    device.alarms_unsupported = True
    for seconds, asked in [
        (0, [INFO, *FIRMWARE]),
        (15, [INFO]),
        (FIRMWARE_CHECK_INTERVAL, [INFO, *FIRMWARE]),
    ]:
        await update(config_entry, clock, seconds)
        assert network.asked(SPEAKER) == asked, seconds
    assert device.sw_version == "1.55.123456"
