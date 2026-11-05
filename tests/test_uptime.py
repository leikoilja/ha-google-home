"""Estimated last boot from existing info checks, using HA's uptime normalization."""

from datetime import timedelta
from http import HTTPStatus
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.const import FIRMWARE_CHECK_INTERVAL

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import SPEAKER_ID, Replies
from .test_coordinators import runtime
from .test_setup import UPTIME_SENSOR, set_up, shown_icons, state
from .test_unsupported_devices import (
    ALARMS,
    NO_ALARMS,
    SPEAKER,
    SUPPORTED,
    UPDATE,
    Reply,
)

# pylint: enable=wrong-import-order

pytestmark = [
    pytest.mark.usefixtures("google", "entity_registry_enabled_by_default"),
    pytest.mark.freeze_time("2026-10-15 12:00:00+00:00"),
]
BOOT = "2026-10-15T11:39:25+00:00"


def info(**fields: object) -> Reply:
    """Return the existing no-params info reply with these invented fields."""
    return HTTPStatus.OK, fields


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param(info(uptime=1234.5), BOOT, id="float"),
        pytest.param(info(uptime=1200), "2026-10-15T11:40:00+00:00", id="int"),
        pytest.param(info(uptime=0), "2026-10-15T12:00:00+00:00", id="zero"),
        pytest.param(info(), STATE_UNKNOWN, id="missing"),
        pytest.param(info(uptime=None), STATE_UNKNOWN, id="null"),
        pytest.param(info(uptime="1234.5"), STATE_UNKNOWN, id="string"),
        pytest.param(info(uptime=True), STATE_UNKNOWN, id="bool"),
        pytest.param(info(uptime=-1), STATE_UNKNOWN, id="negative"),
        pytest.param(info(uptime=1e308), STATE_UNKNOWN, id="duration-overflow"),
        pytest.param(info(uptime=1e11), STATE_UNKNOWN, id="date-overflow"),
        # Five Gregorian 400-year cycles: 730485 days, with no arbitrary age cutoff.
        pytest.param(info(uptime=63113904000), "0026-10-15T12:00:00+00:00", id="old"),
        pytest.param(HTTPStatus.NOT_FOUND, STATE_UNKNOWN, id="404"),
    ],
)
async def test_uptime(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    reply: Reply,
    expected: str,
) -> None:
    """Show a boot timestamp only for a finite, nonnegative and representable uptime."""
    # 1234.5 seconds is 20 minutes 34.5 seconds before noon, truncated by HA.
    replies[SPEAKER][UPDATE] = reply
    await set_up(hass, config_entry)
    assert state(hass, UPTIME_SENSOR) == expected


@pytest.mark.parametrize(
    "reply",
    [
        (HTTPStatus.OK, b'{"uptime":NaN}'),
        (HTTPStatus.OK, b'{"uptime":Infinity}'),
        (HTTPStatus.OK, b'{"uptime":-Infinity}'),
        (HTTPStatus.OK, b'{"uptime":1e400}'),
        (HTTPStatus.OK, []),
        HTTPStatus.NOT_FOUND,
        TimeoutError(),
    ],
    ids=[
        "nan",
        "infinity",
        "negative-infinity",
        "overflow",
        "non-dict",
        "404",
        "timeout",
    ],
)
async def test_uptime_unreadable_reply(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
    reply: Reply,
) -> None:
    """Keep a valid estimate when a later info check returns no usable info."""
    replies[SPEAKER][UPDATE] = info(uptime=1234.5)
    await set_up(hass, config_entry)
    replies[SPEAKER][UPDATE] = reply
    clock.return_value = FIRMWARE_CHECK_INTERVAL
    freezer.tick(timedelta(seconds=FIRMWARE_CHECK_INTERVAL))
    await runtime(config_entry).devices[SPEAKER_ID].async_refresh()
    assert state(hass, UPTIME_SENSOR) == BOOT


async def test_uptime_follow_checks(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Store the sample, suppress jitter, then accept a reboot and recovery from unknown."""
    replies[SPEAKER][UPDATE] = info(uptime=1234.5)
    await set_up(hass, config_entry)
    speaker = runtime(config_entry).devices[SPEAKER_ID]
    first = hass.states.get(UPTIME_SENSOR)
    assert first is not None and first.state == BOOT
    device = speaker.data
    assert device is not None
    assert device.booted_at is not None
    assert device.booted_at.isoformat() == "2026-10-15T11:39:25.500000+00:00"

    # More than HA's tolerance passes, but this isn't a firmware check yet.
    freezer.tick(timedelta(seconds=120))
    clock.return_value = 120
    await speaker.async_refresh()
    assert device.booted_at.isoformat() == "2026-10-15T11:39:25.500000+00:00"
    assert hass.states.get(UPTIME_SENSOR) == first

    # At 12:20 the reply estimates boot three seconds later. HA retains its state.
    freezer.tick(timedelta(seconds=1080))
    clock.return_value = FIRMWARE_CHECK_INTERVAL
    replies[SPEAKER][UPDATE] = info(uptime=2431.5)
    await speaker.async_refresh()
    assert device.booted_at is not None
    assert device.booted_at.isoformat() == "2026-10-15T11:39:28.500000+00:00"
    current = hass.states.get(UPTIME_SENSOR)
    assert current is not None and current.state == BOOT
    assert current.last_changed == first.last_changed

    # A new boot: five minutes before the next check, at 12:40.
    freezer.tick(timedelta(seconds=FIRMWARE_CHECK_INTERVAL))
    clock.return_value += FIRMWARE_CHECK_INTERVAL
    replies[SPEAKER][UPDATE] = info(uptime=300)
    await speaker.async_refresh()
    assert state(hass, UPTIME_SENSOR) == "2026-10-15T12:35:00+00:00"

    freezer.tick(timedelta(seconds=FIRMWARE_CHECK_INTERVAL))
    clock.return_value += FIRMWARE_CHECK_INTERVAL
    replies[SPEAKER][UPDATE] = info()
    await speaker.async_refresh()
    assert speaker.data is not None and speaker.data.booted_at is None
    assert state(hass, UPTIME_SENSOR) == STATE_UNKNOWN

    # Unknown resets HA's baseline: a new estimate 10 seconds away is accepted.
    freezer.tick(timedelta(seconds=FIRMWARE_CHECK_INTERVAL))
    clock.return_value += FIRMWARE_CHECK_INTERVAL
    replies[SPEAKER][UPDATE] = info(uptime=2690)
    await speaker.async_refresh()
    assert state(hass, UPTIME_SENSOR) == "2026-10-15T12:35:10+00:00"


async def test_uptime_api_restart(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Unavailability and a failed check preserve boot time across an API-only restart."""
    replies[SPEAKER][UPDATE] = info(uptime=1234.5)
    await set_up(hass, config_entry)
    speaker = runtime(config_entry).devices[SPEAKER_ID]
    device = speaker.data
    assert device is not None
    booted_at = device.booted_at
    replies[SPEAKER][ALARMS] = TimeoutError()
    for attempt in range(1, 6):
        clock.return_value = attempt * 15
        freezer.tick(timedelta(seconds=15))
        await speaker.async_refresh()
    assert state(hass, UPTIME_SENSOR) == STATE_UNAVAILABLE
    assert device.booted_at == booted_at

    # Alarms answer again, but the due firmware check times out.
    replies[SPEAKER][ALARMS] = SUPPORTED[ALARMS]
    replies[SPEAKER][UPDATE] = TimeoutError()
    clock.return_value = FIRMWARE_CHECK_INTERVAL
    freezer.tick(timedelta(seconds=FIRMWARE_CHECK_INTERVAL - 75))
    await speaker.async_refresh()
    assert state(hass, UPTIME_SENSOR) == BOOT
    assert device.booted_at == booted_at

    # Uptime kept counting through the listener restart; no boot took place.
    clock.return_value += FIRMWARE_CHECK_INTERVAL
    freezer.tick(timedelta(seconds=FIRMWARE_CHECK_INTERVAL))
    replies[SPEAKER][UPDATE] = info(uptime=3634.5)
    await speaker.async_refresh()
    assert device.booted_at == booted_at
    assert state(hass, UPTIME_SENSOR) == BOOT


async def test_uptime_without_alarms(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    entity_registry: er.EntityRegistry,
) -> None:
    """Devices whose alarms return 404 still get uptime and HA's device-class icon."""
    replies[SPEAKER] = {**NO_ALARMS, UPDATE: info(uptime=1234.5)}
    await set_up(hass, config_entry)
    assert hass.states.get("sensor.kitchen_speaker_alarms") is None
    assert state(hass, UPTIME_SENSOR) == BOOT
    assert await shown_icons(hass, entity_registry, [UPTIME_SENSOR]) == {
        UPTIME_SENSOR: None
    }
