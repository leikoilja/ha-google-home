"""Tests for keeping a speaker's data and entities when a reply can't be read.

The speaker answers 200, but with alarms and timers whose fields are missing or of the
wrong type, with a body that isn't valid JSON, or with an alarm volume that isn't a
number. An update keeps what the speaker had and goes on, and the speaker counts as
having answered. An action fails without deleting anything. Alarms and timers whose
status the integration doesn't know are kept, as unknown.
"""

import asyncio
from collections.abc import Mapping
from http import HTTPStatus
from json import JSONDecodeError
import logging
import math
from unittest.mock import Mock

from aiohttp import ClientPayloadError
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_VOLUME,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DO_NOT_DISTURB,
    FETCH_DEVICES_INTERVAL,
    UNANSWERED_UPDATES,
)
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeTimersSensor,
)
from custom_components.google_home.types import JsonDict

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import (
    BEDROOM,
    BEDROOM_ID,
    INVALID_JSON,
    Replies,
    bedroom_speaker,
    kitchen_speaker,
)
from .test_coordinators import BEDROOM_ALARMS, BEDROOM_DND, runtime, update_account
from .test_device_errors import above_debug
from .test_missing_devices import ALARM_ID, TIMER_ID
from .test_sensor import (
    ALARM_IDS,
    TIMER_IDS,
    alarms_json,
    devices_refreshed,
    get_registered_action,
    set_up_devices,
    timers_json,
)
from .test_setup import set_up, state
from .test_unsupported_devices import (
    ALARMS,
    ALWAYS_LABELS,
    DND,
    EVERYTHING,
    FEATURE_LABELS,
    SPEAKER,
    SUPPORTED,
    VOLUME,
    Reply,
    at,
    available,
    entities,
    poll,
    setup,
)

# pylint: enable=wrong-import-order

BEDROOM_VOLUME = "number.bedroom_speaker_alarm_volume"
OTHER_ALARM_ID = "alarm/" + "1" * 36
OTHER_TIMER_ID = "timer/" + "1" * 36
# 2023-11-14 22:13:20 UTC, in milliseconds as the speaker sends it
FIRE_TIME = 1700000000000


def alarm(alarm_id: str = ALARM_ID, **fields: object) -> dict[str, object]:
    """Return a set alarm as the speaker sends it, with these fields changed."""
    return {"id": alarm_id, "fire_time": FIRE_TIME, "status": 1, **fields}


def timer(timer_id: str = TIMER_ID, **fields: object) -> dict[str, object]:
    """Return a set one-minute timer as the speaker sends it, with these fields changed."""
    return {
        "id": timer_id,
        "fire_time": FIRE_TIME,
        "original_duration": 60000,
        "status": 1,
        **fields,
    }


def lists(
    alarms: list[object] | None = None, timers: list[object] | None = None
) -> dict[str, object]:
    """Return a reply to the alarms request with these alarms and timers."""
    return {"alarm": alarms or [], "timer": timers or []}


def unknown_reply(reply: object) -> str:
    """Return the error logged for a reply to the alarms request that can't be read."""
    return (
        "Failed to parse fetched alarms and timers for device Device 0 - API returned "
        f"unknown json structure. Received = {reply}"
    )


# The alarms and timers the speaker has when a test starts
FIRST = lists([alarm()], [timer()])


def ids(device: GoogleHomeDevice) -> tuple[list[str], list[str]]:
    """Return the IDs of the device's alarms and of its timers."""
    return (
        [item.alarm_id for item in device.get_sorted_alarms()],
        [item.timer_id for item in device.get_sorted_timers()],
    )


def sensors_of(
    by_label: Mapping[str, object],
) -> tuple[GoogleHomeAlarmsSensor, GoogleHomeTimersSensor]:
    """Return the alarms and timers sensors among a device's entities."""
    alarms, timers = by_label["alarms"], by_label["timers"]
    assert isinstance(alarms, GoogleHomeAlarmsSensor)
    assert isinstance(timers, GoogleHomeTimersSensor)
    return alarms, timers


def errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the messages that the integration logged as errors."""
    return [message for level, message in above_debug(caplog) if level == "ERROR"]


# Replies to the alarms request whose structure can't be read. Each also has other
# alarms or timers that could be, which must not replace those the speaker had.
STRUCTURAL = [
    pytest.param(
        {"alarm": [{"id": OTHER_ALARM_ID, "status": 1}], "timer": []}, id="no-fire-time"
    ),
    pytest.param({"alarm": [alarm(OTHER_ALARM_ID, id=1)], "timer": []}, id="id-number"),
    pytest.param(
        {"alarm": [alarm(OTHER_ALARM_ID, status="1")], "timer": []}, id="status-text"
    ),
    pytest.param(
        {"alarm": [alarm(OTHER_ALARM_ID, status=None)], "timer": []}, id="status-null"
    ),
    pytest.param(
        {"alarm": [alarm(OTHER_ALARM_ID, status=True)], "timer": []}, id="status-true"
    ),
    pytest.param(
        {"alarm": [alarm(OTHER_ALARM_ID, fire_time=True)], "timer": []},
        id="fire-time-true",
    ),
    pytest.param(
        {"alarm": [alarm(OTHER_ALARM_ID, fire_time=math.nan)], "timer": []},
        id="fire-time-nan",
    ),
    pytest.param(
        {"alarm": [], "timer": [timer(OTHER_TIMER_ID, original_duration=False)]},
        id="duration-false",
    ),
    pytest.param(
        {"alarm": [], "timer": [timer(OTHER_TIMER_ID, original_duration=math.inf)]},
        id="duration-infinity",
    ),
    # A timer that is set, so its time left isn't shown, but must still be a number
    pytest.param(
        {"alarm": [], "timer": [timer(OTHER_TIMER_ID, remaining_duration=True)]},
        id="remaining-true",
    ),
    pytest.param(
        {
            "alarm": [],
            "timer": [timer(OTHER_TIMER_ID, remaining_duration=math.nan)],
        },
        id="remaining-nan",
    ),
    pytest.param(
        {
            "alarm": [],
            "timer": [timer(OTHER_TIMER_ID, remaining_duration=math.inf)],
        },
        id="remaining-infinity",
    ),
    pytest.param({"alarm": [alarm(OTHER_ALARM_ID)], "timer": None}, id="timers-null"),
    pytest.param({"alarm": [OTHER_ALARM_ID], "timer": []}, id="alarm-not-object"),
    # The timers can be read, but not the alarm
    pytest.param(
        {
            "alarm": [alarm(OTHER_ALARM_ID, status="1")],
            "timer": [timer(OTHER_TIMER_ID)],
        },
        id="partly-valid",
    ),
    pytest.param([alarm(OTHER_ALARM_ID)], id="list"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("reply", STRUCTURAL)
def test_reply_that_cant_be_read_keeps_alarms_and_timers(
    clock: Mock, caplog: pytest.LogCaptureFixture, reply: object
) -> None:
    """Keep the alarms and timers the speaker had, and log one error, when its reply can't be read.

    The update doesn't count it as having got them, the speaker counts as having
    answered, and its settings are still asked.
    """
    client, _, network = setup({**SUPPORTED, ALARMS: (HTTPStatus.OK, FIRST)})
    [device] = client.google_devices
    poll(client, clock, at(0))
    assert ids(device) == ([ALARM_ID], [TIMER_ID])
    network.asked(SPEAKER)
    network.replies[SPEAKER][ALARMS] = (HTTPStatus.OK, reply)

    for seconds in (at(0, 15), at(0, 30)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == EVERYTHING

    assert ids(device) == ([ALARM_ID], [TIMER_ID])
    assert device.polled_snapshots == 1
    assert device.statuses[API_ENDPOINT_ALARMS, True] == HTTPStatus.OK
    assert (device.reachable, device.unanswered_updates) == (True, 0)
    assert errors(caplog) == [unknown_reply(reply)]


@pytest.mark.parametrize(
    ("first", "then"),
    [
        # The alarms can be read, and change; a timer can't be converted
        pytest.param(
            {
                "alarm": [alarm(OTHER_ALARM_ID)],
                "timer": [timer(original_duration=1e20)],
            },
            ([ALARM_ID], [TIMER_ID]),
            id="duration-too-long",
        ),
        # A paused timer, whose time left is shown
        pytest.param(
            {
                "alarm": [alarm(OTHER_ALARM_ID)],
                "timer": [timer(fire_time=None, status=2, remaining_duration=1e20)],
            },
            ([ALARM_ID], [TIMER_ID]),
            id="time-left-too-long",
        ),
        # The timers can be read, and change; an alarm's fire time is after year 9999
        pytest.param(
            {"alarm": [alarm(fire_time=1e17)], "timer": [timer(OTHER_TIMER_ID)]},
            ([ALARM_ID], [TIMER_ID]),
            id="fire-time-too-late",
        ),
        # A whole number too large for a float, which isn't converted to check it
        pytest.param(
            {"alarm": [alarm(fire_time=10**400)], "timer": []},
            ([ALARM_ID], [TIMER_ID]),
            id="huge-fire-time",
        ),
        pytest.param(
            {"alarm": [], "timer": [timer(original_duration=10**400)]},
            ([ALARM_ID], [TIMER_ID]),
            id="huge-duration",
        ),
    ],
)
def test_reply_whose_times_cant_be_converted_keeps_both_lists(
    first: dict[str, object], then: tuple[list[str], list[str]]
) -> None:
    """Keep both lists when a number in the reply is too large to convert, whichever list it's in."""
    device = GoogleHomeDevice("device-id", "Kitchen", "token")
    assert device.set_alarms_and_timers(FIRST)

    assert not device.set_alarms_and_timers(first)

    assert ids(device) == then


def test_unknown_statuses_are_kept_and_sorted_last(clock: Mock) -> None:
    """List alarms and timers whose status the integration doesn't know as unknown, after the others.

    An unknown one is never the sensor's state, even with a fire time. The reply
    counts as one the update got.
    """
    client, _, network = setup(SUPPORTED)
    poll(client, clock, at(0))
    network.replies[SPEAKER][ALARMS] = (
        HTTPStatus.OK,
        {
            "alarm": [
                alarm("alarm/unknown", fire_time=FIRE_TIME - 60000, status=6),
                alarm("alarm/inactive", fire_time=FIRE_TIME - 120000, status=4),
                alarm("alarm/set"),
            ],
            "timer": [
                timer("timer/unknown", fire_time=FIRE_TIME - 60000, status=7),
                timer("timer/set"),
            ],
        },
    )
    devices = poll(client, clock, at(0, 15))
    [device] = client.google_devices
    alarms_sensor, timers_sensor = sensors_of(
        entities(client, Mock(data=devices), "device0")
    )

    assert device.polled_snapshots == 2
    alarms = alarms_sensor.extra_state_attributes["alarms"]
    timers = timers_sensor.extra_state_attributes["timers"]
    assert [(item["alarm_id"], item["status"]) for item in alarms] == [
        ("alarm/set", "set"),
        # Last, by fire time
        ("alarm/inactive", "inactive"),
        ("alarm/unknown", "unknown"),
    ]
    assert [(item["timer_id"], item["status"]) for item in timers] == [
        ("timer/set", "set"),
        ("timer/unknown", "unknown"),
    ]
    # The set ones', although the unknown ones' fire times come first
    assert alarms_sensor.state == alarms[0]["local_time_iso"]
    assert timers_sensor.state == timers[0]["local_time_iso"]

    # With only the unknown ones
    network.replies[SPEAKER][ALARMS] = (
        HTTPStatus.OK,
        {
            "alarm": [alarm("alarm/unknown", status=6)],
            "timer": [timer("timer/unknown", status=7)],
        },
    )
    devices = poll(client, clock, at(0, 30))
    by_label = entities(client, Mock(data=devices), "device0")
    alarms_sensor, timers_sensor = sensors_of(dict(by_label))

    assert device.polled_snapshots == 3
    # Only its state: the sensor itself is available
    assert (alarms_sensor.state, timers_sensor.state) == ("unavailable", "unavailable")
    assert alarms_sensor.extra_state_attributes["next_alarm_status"] == "unknown"
    assert timers_sensor.extra_state_attributes["next_timer_status"] == "unknown"
    assert available(by_label) == FEATURE_LABELS | ALWAYS_LABELS


@pytest.mark.parametrize(
    ("label", "path"),
    [
        pytest.param(ALARMS, API_ENDPOINT_ALARMS, id="alarms"),
        pytest.param(VOLUME, API_ENDPOINT_ALARM_VOLUME, id="volume"),
        pytest.param(DND, API_ENDPOINT_DO_NOT_DISTURB, id="do-not-disturb"),
    ],
)
def test_reply_that_isnt_valid_json(
    clock: Mock, caplog: pytest.LogCaptureFixture, label: str, path: str
) -> None:
    """Keep what the speaker had when a reply isn't valid JSON, and log it once until an update works.

    The speaker counts as having answered, also for more updates in a row than make
    its entities unavailable when it doesn't answer, and it's asked the rest.
    """
    client, _, network = setup(SUPPORTED)
    [device] = client.google_devices
    poll(client, clock, at(0))
    # The volume and Do Not Disturb that SUPPORTED gives
    assert (device.alarm_volume, device.do_not_disturb) == (70, True)
    network.asked(SPEAKER)
    network.replies[SPEAKER][label] = (
        HTTPStatus.OK,
        JSONDecodeError("Expecting value", "<html>", 0),
    )

    for update in range(UNANSWERED_UPDATES + 1):
        poll(client, clock, at(0, 15 * (update + 1)))
        assert network.asked(SPEAKER) == EVERYTHING

    assert ids(device) == ([ALARM_ID], [])
    assert (device.alarm_volume, device.do_not_disturb) == (70, True)
    # Only the updates whose alarms could be read got them
    assert device.polled_snapshots == (1 if label == ALARMS else UNANSWERED_UPDATES + 2)
    assert device.statuses[path, True] == HTTPStatus.OK
    assert (device.available, device.reachable, device.unanswered_updates) == (
        True,
        True,
        0,
    )
    assert available(entities(client, Mock(data={"device0": device}), "device0")) == (
        FEATURE_LABELS | ALWAYS_LABELS
    )
    invalid = (
        f"Device 0 sent a reply to {path} that isn't valid JSON: Expecting value: "
        "line 1 column 1 (char 0)"
    )
    assert above_debug(caplog) == [("ERROR", invalid)]

    network.replies[SPEAKER] = dict(SUPPORTED)
    poll(client, clock, at(5))
    network.replies[SPEAKER][label] = (
        HTTPStatus.OK,
        JSONDecodeError("Expecting value", "<html>", 0),
    )
    poll(client, clock, at(5, 15))

    assert above_debug(caplog) == [
        ("ERROR", invalid),
        ("INFO", "Updating Device 0 works again"),
        ("ERROR", invalid),
    ]


@pytest.mark.parametrize(
    "volume",
    [
        pytest.param("loud", id="text"),
        pytest.param(None, id="null"),
        pytest.param(True, id="true"),
        pytest.param(math.inf, id="infinity"),
        pytest.param(math.nan, id="nan"),
    ],
)
def test_alarm_volume_that_isnt_a_number(
    clock: Mock, caplog: pytest.LogCaptureFixture, volume: object
) -> None:
    """Keep the alarm volume the speaker had when it sends one that isn't a number, and log it once until an update works."""
    client, _, network = setup(SUPPORTED)
    [device] = client.google_devices
    poll(client, clock, at(0))
    invalid: Reply = (HTTPStatus.OK, {"volume": volume})
    network.replies[SPEAKER][VOLUME] = invalid

    for seconds in (at(0, 15), at(0, 30), at(0, 45)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER)[-1] == DND

    assert device.alarm_volume == 70
    message = f"Device 0 sent an alarm volume that isn't a number: {volume}"
    assert above_debug(caplog) == [("ERROR", message)]

    network.replies[SPEAKER][VOLUME] = (HTTPStatus.OK, {"volume": 0.5})
    poll(client, clock, at(1))
    assert device.alarm_volume == 50
    network.replies[SPEAKER][VOLUME] = invalid
    poll(client, clock, at(1, 15))

    assert device.alarm_volume == 50
    assert above_debug(caplog) == [
        ("ERROR", message),
        ("INFO", "Updating Device 0 works again"),
        ("ERROR", message),
    ]


def test_alarm_volume_reply_without_the_volume_is_only_debugged(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep the alarm volume, logging only for debugging, when the reply leaves it out, as before."""
    client, _, network = setup(SUPPORTED)
    [device] = client.google_devices
    poll(client, clock, at(0))
    network.replies[SPEAKER][VOLUME] = (HTTPStatus.OK, {"level": 0.5})

    poll(client, clock, at(0, 15))

    assert device.alarm_volume == 70
    assert above_debug(caplog) == []


def test_null_after_reply_that_cant_be_read_doesnt_end_the_failure(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Count a reply of JSON null as one that can't be read, so it doesn't make the update work.

    Only a reply that can be read logs that updating works again.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    client, _, network = setup(SUPPORTED)
    poll(client, clock, at(0))
    malformed = {"alarm": [{"id": ALARM_ID, "status": 1}], "timer": []}
    for seconds, reply in (
        (at(0, 15), (HTTPStatus.OK, malformed)),
        (at(0, 30), (HTTPStatus.OK, None)),
        (at(0, 45), SUPPORTED[ALARMS]),
    ):
        network.replies[SPEAKER][ALARMS] = reply
        poll(client, clock, seconds)

    assert above_debug(caplog) == [
        ("ERROR", unknown_reply(malformed)),
        ("INFO", "Updating Device 0 works again"),
    ]
    assert ("DEBUG", unknown_reply(None)) in [
        (record.levelname, record.getMessage()) for record in caplog.records
    ]


def alarms_shown(hass: HomeAssistant, entity_id: str) -> object:
    """Return the alarms attribute of an alarms sensor, which only an available one has."""
    entity_state = hass.states.get(entity_id)
    assert entity_state is not None
    return entity_state.attributes["alarms"]


@pytest.mark.usefixtures("google", "two_speakers")
@pytest.mark.parametrize(
    "unreadable",
    [
        # Without its fire time, the alarm can't be read
        pytest.param(
            (HTTPStatus.OK, {"alarm": [{"id": ALARM_ID, "status": 1}], "timer": []}),
            id="malformed",
        ),
        pytest.param((HTTPStatus.OK, INVALID_JSON), id="invalid-json"),
    ],
)
async def test_speaker_whose_alarms_cant_be_read_keeps_its_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    replies: Replies,
    unreadable: Reply,
) -> None:
    """Add a speaker's entities at setup, and keep them available, while its alarms reply can't be read.

    Its updates work. Its alarms sensor shows no alarms until a reply can be read, and
    then keeps them while one can't.
    """
    replies[BEDROOM][ALARMS] = unreadable

    await set_up(hass, config_entry)

    coordinator = runtime(config_entry).devices[BEDROOM_ID]
    assert coordinator.last_update_success
    assert alarms_shown(hass, BEDROOM_ALARMS) == []
    assert state(hass, BEDROOM_DND) == "on"

    replies[BEDROOM][ALARMS] = SUPPORTED[ALARMS]
    await coordinator.async_refresh()
    replies[BEDROOM][ALARMS] = unreadable
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert state(hass, BEDROOM_ALARMS) == "2023-11-14T14:13:20-08:00"
    assert state(hass, BEDROOM_DND) == "on"


@pytest.mark.parametrize(
    ("later", "added"),
    [
        pytest.param((HTTPStatus.OK, INVALID_JSON), True, id="invalid-json"),
        # An answer that is cut off isn't one
        pytest.param(ClientPayloadError("cut off"), False, id="cut-off"),
    ],
)
async def test_speaker_found_later_gets_entities_once_it_answers_unreadably(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
    later: Reply,
    added: bool,
) -> None:
    """Add a speaker's entities once it answers, also with replies that can't be read.

    Its first update timed out, so it got none then. Nothing from those replies is
    shown: it has no alarms, and its settings are the defaults.
    """
    await set_up(hass, config_entry)
    google.return_value = [kitchen_speaker(), bedroom_speaker()]
    replies[BEDROOM] = {**SUPPORTED, ALARMS: TimeoutError()}
    clock.return_value = FETCH_DEVICES_INTERVAL
    await update_account(hass, config_entry)
    coordinator = runtime(config_entry).devices[BEDROOM_ID]
    assert coordinator.data is not None
    assert not coordinator.data.available
    assert hass.states.get(BEDROOM_ALARMS) is None

    replies[BEDROOM] = {**SUPPORTED, ALARMS: later, VOLUME: later, DND: later}
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert coordinator.last_update_success
    assert (hass.states.get(BEDROOM_ALARMS) is not None) is added
    if added:
        assert alarms_shown(hass, BEDROOM_ALARMS) == []
        assert (state(hass, BEDROOM_DND), state(hass, BEDROOM_VOLUME)) == ("off", "0")


# The alarms and timers that set_up_devices gives each device, as its last poll saw
LAST_POLL: JsonDict = {
    "alarm": alarms_json(["alarm/from-last-poll"]),
    "timer": timers_json(["timer/from-last-poll"]),
}


@pytest.mark.parametrize(
    "reply",
    [
        # Without its fire time, the alarm can't be read
        pytest.param(
            {"alarm": [{"id": "alarm/from-last-poll", "status": 1}], "timer": []},
            id="malformed",
        ),
        # The timers can be read, but not the alarm
        pytest.param(
            {
                "alarm": [{"id": ALARM_IDS[0], "fire_time": "soon", "status": 1}],
                "timer": timers_json(TIMER_IDS),
            },
            id="partly-valid",
        ),
        pytest.param(None, id="null"),
        pytest.param(
            JSONDecodeError("Expecting value", "<html>", 0), id="invalid-json"
        ),
    ],
)
@pytest.mark.parametrize(
    ("action", "sensor_class", "data"),
    [
        ("delete_all_alarms", GoogleHomeAlarmsSensor, {}),
        ("delete_all_timers", GoogleHomeTimersSensor, {}),
        ("delete_alarm", GoogleHomeAlarmsSensor, {"alarm_id": "alarm/from-last-poll"}),
        ("delete_timer", GoogleHomeTimersSensor, {"timer_id": "timer/from-last-poll"}),
    ],
)
def test_delete_fails_when_reply_cant_be_read(
    action: str,
    sensor_class: type[GoogleHomeBaseEntity],
    data: dict[str, str],
    reply: JsonDict | Exception | None,
) -> None:
    """Fail with the error for alarms and timers it couldn't fetch, and delete nothing from that device.

    Not even what the last poll saw, which the device may no longer have. The other
    device, whose reply can be read, still deletes and refreshes.
    """
    func, _ = get_registered_action(action)
    sensors, delete, coordinators = set_up_devices(
        sensor_class, {"Kitchen": reply, "Bedroom": LAST_POLL}
    )

    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(func(sensors, Mock(data=data)))

    assert err.value.translation_key == "alarms_and_timers_not_fetched"
    assert err.value.translation_placeholders == {"device": "Kitchen"}
    assert [c.kwargs["device"].name for c in delete.await_args_list] == ["Bedroom"]
    assert devices_refreshed(coordinators) == ["Bedroom"]
    kitchen = coordinators["Kitchen"].data
    assert [alarm.alarm_id for alarm in kitchen.get_sorted_alarms()] == [
        "alarm/from-last-poll"
    ]
    assert [timer.timer_id for timer in kitchen.get_sorted_timers()] == [
        "timer/from-last-poll"
    ]
