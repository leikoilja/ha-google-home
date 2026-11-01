"""Tests for the diagnostics that a user downloads to attach to a bug report.

Home Assistant's diagnostics view builds the file, as when the user selects
**Download diagnostics**.
"""

from http import HTTPStatus
import json
from typing import cast
from unittest.mock import Mock

import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion

from custom_components.google_home.const import (
    CONF_ANDROID_ID,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
    FETCH_DEVICES_INTERVAL,
)

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    SPEAKER_CLOUD_ID,
    SPEAKER_ID,
    SPEAKER_NAME,
    Replies,
    bedroom_speaker,
    kitchen_speaker,
)
from .test_coordinators import REJECTING, runtime, update_account
from .test_missing_devices import ALARM_ID, answered, found
from .test_setup import set_up
from .test_unsupported_devices import ALARMS, SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order

# Each stored credential, token and address has its own invented value, so a leak
# shows which one it is
USERNAME = "diagnostics-user@example.com"
PASSWORD = "invented-app-password"
MASTER_TOKEN = "aas_et/" + "m" * 216
ANDROID_ID = "a1b2c3d4e5f60718"
LOCAL_AUTH_TOKEN = "invented-local-token-" + "t" * 87
KNOWN_HOST = "10.0.0.9"
# A Cast device on the network that Google's list doesn't have, which diagnostics
# only counts
TV_CLOUD_ID = "living-room-tv-cloud-id"
TV_NAME = "Living Room TV"
TV = "10.0.0.7"
BEDROOM_TOKEN = "invented-bedroom-token-" + "b" * 85
SECRETS = [
    USERNAME,
    PASSWORD,
    MASTER_TOKEN,
    ANDROID_ID,
    LOCAL_AUTH_TOKEN,
    SPEAKER,
    KNOWN_HOST,
    TV_NAME,
    TV,
]
# An alarm and a timer with labels the user typed, which diagnostics keeps
ALARMS_REPLY = {
    "alarm": [
        {
            "id": ALARM_ID,
            "fire_time": 1700000000000,
            "status": 1,
            "label": "Take the bins out",
        }
    ],
    "timer": [
        {
            "id": "timer/0b0f3c49-2d8e-4b8a-9a43-5f1d6c7e8a90",
            "fire_time": 1700000600000,
            "original_duration": 600000,
            "remaining_duration": 600000,
            "status": 1,
            "label": "Pasta",
        }
    ],
}


@pytest.mark.freeze_time("2026-10-15 12:00:00+00:00")
async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    google: Mock,
    replies: Replies,
    snapshot: SnapshotAssertion,
) -> None:
    """Show the settings and the speaker's state, without credentials or addresses.

    The speaker's last alarms reply is kept as it came, with its labels. The entry's
    title, which is the account's email address, is left out. mDNS reported the
    speaker and a TV that Google doesn't list, which is only counted. The time is
    shown in Home Assistant's time zone, US/Pacific in tests.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        data={
            CONF_MASTER_TOKEN: MASTER_TOKEN,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_ANDROID_ID: ANDROID_ID,
        },
        options={CONF_UPDATE_INTERVAL: 30, CONF_KNOWN_HOSTS: [KNOWN_HOST]},
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    google.return_value = [
        found(
            SPEAKER_ID,
            SPEAKER,
            token=LOCAL_AUTH_TOKEN,
            name=SPEAKER_NAME,
            cloud_device_id=SPEAKER_CLOUD_ID,
        )
    ]
    replies[SPEAKER][ALARMS] = (HTTPStatus.OK, ALARMS_REPLY)
    await set_up(hass, entry)
    found_devices = runtime(entry).client.found_devices
    found_devices.async_device_found(SPEAKER_CLOUD_ID, SPEAKER_NAME, SPEAKER)
    found_devices.async_device_found(TV_CLOUD_ID, TV_NAME, TV)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics == snapshot
    text = json.dumps(diagnostics)
    assert [secret for secret in SECRETS if secret in text] == []
    assert diagnostics["data"] == {
        CONF_MASTER_TOKEN: REDACTED,
        CONF_USERNAME: REDACTED,
        CONF_PASSWORD: REDACTED,
        CONF_ANDROID_ID: REDACTED,
    }
    assert diagnostics["options"] == {
        CONF_UPDATE_INTERVAL: 30,
        CONF_KNOWN_HOSTS: REDACTED,
    }
    speaker = cast(dict[str, dict[str, object]], diagnostics["devices"])[SPEAKER_ID]
    assert (speaker["ip_address"], speaker["auth_token"]) == (REDACTED, REDACTED)
    assert speaker["alarms_reply"] == ALARMS_REPLY
    assert speaker["mdns_reported"] is True
    assert diagnostics["mdns_reported_not_listed"] == 1
    assert diagnostics["now"] == "2026-10-15T05:00:00-07:00"


@pytest.mark.usefixtures("google")
async def test_diagnostics_keep_unknown_alarms_reply(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    replies: Replies,
) -> None:
    """Keep an alarms reply that the integration can't read, to show what came."""
    unknown = {"alarms": [{"id": ALARM_ID}]}
    replies[SPEAKER][ALARMS] = (HTTPStatus.OK, unknown)
    await set_up(hass, config_entry)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    devices = cast(dict[str, dict[str, object]], diagnostics["devices"])
    assert devices[SPEAKER_ID]["alarms_reply"] == unknown


@pytest.mark.usefixtures("google")
async def test_diagnostics_leave_out_error_text(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    replies: Replies,
) -> None:
    """Show only the type of a speaker's last error, as its text can include the address."""
    await set_up(hass, config_entry)
    replies[SPEAKER][ALARMS] = ValueError(f"Can't reach {SPEAKER}:8443")
    await runtime(config_entry).devices[SPEAKER_ID].async_refresh()

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    speaker = cast(dict[str, dict[str, object]], diagnostics["devices"])[SPEAKER_ID]
    assert (speaker["last_update_success"], speaker["last_exception"]) == (
        False,
        "ValueError",
    )
    assert SPEAKER not in json.dumps(diagnostics)


@pytest.mark.usefixtures("replies")
async def test_diagnostics_of_speaker_google_stops_listing(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
) -> None:
    """Show only how the last update went for a speaker that Google no longer lists.

    Once the second home graph without it removes it, it isn't shown at all. If mDNS
    reports it, it counts as a Cast device that Google's list doesn't have.
    """
    await set_up(hass, config_entry)
    google.return_value = []
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    unlisted = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    runtime(config_entry).client.found_devices.async_device_found(
        SPEAKER_CLOUD_ID, SPEAKER_NAME, SPEAKER
    )
    clock.return_value = 2 * FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)
    removed = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert (unlisted["devices"], unlisted["mdns_reported_not_listed"]) == (
        {SPEAKER_ID: {"last_update_success": True, "last_exception": None}},
        0,
    )
    assert (removed["devices"], removed["mdns_reported_not_listed"]) == ({}, 1)


async def test_diagnostics_of_speaker_whose_first_update_fails(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
) -> None:
    """Show the reply that makes a newly listed speaker's first update fail.

    Its coordinator has no data until one of its updates works, but Google lists it.
    """
    await set_up(hass, config_entry)
    google.return_value = [
        kitchen_speaker(),
        found(BEDROOM_ID, BEDROOM, token=BEDROOM_TOKEN, name="Bedroom speaker"),
    ]
    # Without its fire time, the alarm can't be read
    malformed = {"alarm": [{"id": ALARM_ID, "status": 1}], "timer": []}
    replies[BEDROOM] = {**SUPPORTED, ALARMS: (HTTPStatus.OK, malformed)}
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    bedroom = cast(dict[str, dict[str, object]], diagnostics["devices"])[BEDROOM_ID]
    expected = {
        "name": "Bedroom speaker",
        "last_update_success": False,
        "last_exception": "KeyError",
        "ip_address": REDACTED,
        "auth_token": REDACTED,
        "alarms_reply": malformed,
    }
    assert {key: bedroom.get(key) for key in expected} == expected
    text = json.dumps(diagnostics)
    assert [secret for secret in (BEDROOM, BEDROOM_TOKEN) if secret in text] == []


async def test_diagnostics_mdns_reports_by_speaker(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
) -> None:
    """Show whether mDNS reported each speaker, unknown for one without Google's ID.

    The bedroom speaker rejects every token, which leaves Google's list to fetch
    again, but the list and so the count are still known.
    """
    hall = found("hall", "10.0.0.4", name="Hall speaker")
    hall.cloud_device_id = None
    google.return_value = [kitchen_speaker(), bedroom_speaker(), hall]
    replies[BEDROOM] = dict(REJECTING)
    replies["10.0.0.4"] = dict(SUPPORTED)
    await set_up(hass, config_entry)
    found_devices = runtime(config_entry).client.found_devices
    found_devices.async_device_found(SPEAKER_CLOUD_ID, SPEAKER_NAME, SPEAKER)
    found_devices.async_device_found(TV_CLOUD_ID, TV_NAME, TV)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    devices = cast(dict[str, dict[str, object]], diagnostics["devices"])
    account = cast(dict[str, object], diagnostics["account"])
    assert {
        device_id: info["mdns_reported"] for device_id, info in devices.items()
    } == {
        SPEAKER_ID: True,
        BEDROOM_ID: False,
        "hall": None,
    }
    assert (
        account["google_devices_fetched"],
        diagnostics["mdns_reported_not_listed"],
    ) == (
        False,
        1,
    )


@pytest.mark.usefixtures("replies")
async def test_diagnostics_before_google_list_is_known(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    google: Mock,
) -> None:
    """Leave the count of Cast devices that Google doesn't list unknown without a list.

    Setup goes on without devices when Google's list can't be fetched.
    """
    google.side_effect = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    await set_up(hass, config_entry)
    runtime(config_entry).client.found_devices.async_device_found(
        TV_CLOUD_ID, TV_NAME, TV
    )

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, config_entry
    )

    assert (diagnostics["devices"], diagnostics["mdns_reported_not_listed"]) == (
        {},
        None,
    )
