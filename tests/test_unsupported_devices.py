"""Tests for not asking devices for alarms, timers and settings they don't have."""

import asyncio
from collections.abc import Mapping
from http import HTTPStatus
from json import JSONDecodeError
from unittest.mock import AsyncMock, MagicMock, Mock

from aiohttp import ContentTypeError
import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.button import RebootButton
from custom_components.google_home.const import (
    API_ENDPOINT_ALARM_VOLUME,
    API_ENDPOINT_ALARMS,
    API_ENDPOINT_DO_NOT_DISTURB,
    API_ENDPOINT_EUREKA_INFO,
    API_ENDPOINT_REBOOT,
)
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.exceptions import AlarmsAndTimersNotFetched
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeTimersSensor,
)
from custom_components.google_home.switch import DoNotDisturbSwitch

from .test_missing_devices import (
    ALARM_ID,
    HOUR,
    MINUTE,
    add_entities,
    found,
    make_client,
)

ALARMS = "alarms"
VOLUME = "alarm volume"
DND = "Do Not Disturb"
INFO = "info"
REBOOT = "reboot"
ENDPOINTS = {
    API_ENDPOINT_ALARMS: ALARMS,
    API_ENDPOINT_ALARM_VOLUME: VOLUME,
    API_ENDPOINT_DO_NOT_DISTURB: DND,
    API_ENDPOINT_EUREKA_INFO: INFO,
    API_ENDPOINT_REBOOT: REBOOT,
}
# What every update asks a device
EVERYTHING = [ALARMS, VOLUME, DND]
# What a device whose alarms don't answer 200 is asked in an update: its info too,
# for the available attribute of its device sensor
WITH_INFO = [ALARMS, INFO, VOLUME, DND]

# What a device answers: a status, a status and a body, or what the request raises.
# A body that is an exception is what reading it raises.
type Reply = HTTPStatus | tuple[HTTPStatus, object] | Exception

# make_client gives each device this token
OLD_TOKEN = "token"
NEW_TOKEN = "y" * 108
NEWER_TOKEN = "z" * 108

FEATURES: list[type[GoogleHomeBaseEntity]] = [
    GoogleHomeAlarmsSensor,
    GoogleHomeTimersSensor,
    DoNotDisturbSwitch,
    AlarmVolumeNumber,
]
ALWAYS: list[type[GoogleHomeBaseEntity]] = [GoogleHomeDeviceSensor, RebootButton]
FEATURE_LABELS = {"alarms", "timers", "Do Not Disturb", "alarm volume"}
ALWAYS_LABELS = {"device", "reboot"}


def info(**capabilities: object) -> tuple[HTTPStatus, object]:
    """Return a device's info, listing a few invented features and these."""
    return HTTPStatus.OK, {
        "name": "Speaker",
        "device_info": {
            "capabilities": {
                "audio_supported": True,
                "display_supported": False,
                **capabilities,
            }
        },
    }


# A Google or Nest speaker
SUPPORTED: dict[str, Reply] = {
    ALARMS: (
        HTTPStatus.OK,
        {
            "alarm": [{"id": ALARM_ID, "fire_time": 1700000000000, "status": 1}],
            "timer": [],
        },
    ),
    VOLUME: (HTTPStatus.OK, {"volume": 0.7}),
    DND: (HTTPStatus.OK, {"notifications_enabled": False}),
    INFO: info(assistant_supported=True),
    REBOOT: (HTTPStatus.OK, {}),
}
# As a Chromecast Audio answers: "not found" for alarms and their settings, and
# info that leaves out assistant_supported
NO_ALARMS: dict[str, Reply] = {
    ALARMS: HTTPStatus.NOT_FOUND,
    VOLUME: HTTPStatus.NOT_FOUND,
    DND: HTTPStatus.NOT_FOUND,
    INFO: info(),
    REBOOT: (HTTPStatus.OK, {}),
}


class Network:
    """Devices that answer each request as `replies` says, by address, and record it.

    It records each call the client makes on the session, not what goes over the
    wire. Closing an answer from an address in `close_errors` raises that error.
    """

    def __init__(self) -> None:
        """Start with no devices."""
        self.replies: dict[str, dict[str, Reply]] = {}
        self.close_errors: dict[str, Exception] = {}
        # Each session.get() call: its URL and keyword arguments
        self.gets: list[tuple[str, dict[str, object]]] = []
        self._asked: list[tuple[str, str]] = []
        self.session = Mock(
            request=Mock(side_effect=lambda _method, url, **_: self._answer(url)),
            get=Mock(side_effect=self._get),
        )

    def _get(self, url: str, **kwargs: object) -> MagicMock:
        self.gets.append((url, kwargs))
        return self._answer(url)

    def _answer(self, url: str) -> MagicMock:
        host, endpoint = url.removeprefix("https://").split("/", 1)
        address = host.rsplit(":", 1)[0]
        self._asked.append((address, ENDPOINTS[endpoint]))
        reply = self.replies[address][ENDPOINTS[endpoint]]
        response = MagicMock()
        if isinstance(reply, Exception):
            response.__aenter__.side_effect = reply
            return response
        status, body = reply if isinstance(reply, tuple) else (reply, None)
        response.__aenter__.return_value = MagicMock(
            status=status,
            json=AsyncMock(side_effect=body)
            if isinstance(body, Exception)
            else AsyncMock(return_value=body),
            read=AsyncMock(side_effect=body)
            if isinstance(body, Exception)
            else AsyncMock(return_value=body if isinstance(body, bytes) else b"{}"),
        )
        if close_error := self.close_errors.get(address):
            response.__aexit__.side_effect = close_error
        return response

    def asked(self, address: str) -> list[str]:
        """Return what the device at this address was asked since the last call, in order."""
        asked = [endpoint for to, endpoint in self._asked if to == address]
        self._asked = [request for request in self._asked if request[0] != address]
        return asked


SPEAKER = "10.0.0.2"
OTHER = "10.0.0.3"


def at(minutes: int, seconds: int = 0) -> int:
    """Return this time since setup, in seconds."""
    return minutes * MINUTE + seconds


def setup(
    *replies: Mapping[str, Reply],
) -> tuple[GlocaltokensApiClient, Mock, Network]:
    """Return a client whose devices, at SPEAKER and then OTHER, answer as given.

    Also return its fake glocaltokens, and the network to change the answers.
    """
    network = Network()
    addresses = [SPEAKER, OTHER][: len(replies)]
    for address, device_replies in zip(addresses, replies, strict=True):
        network.replies[address] = dict(device_replies)
    client, glocaltokens = make_client(*addresses, session=network.session)
    # Unless a test says otherwise, Google gives the devices the same tokens again
    glocaltokens.get_google_devices.return_value = [
        found(device.device_id, device.ip_address, OLD_TOKEN)
        for device in client.google_devices
    ]
    return client, glocaltokens, network


def reload(network: Network, *addresses: str) -> GlocaltokensApiClient:
    """Return the client that reloading the integration creates.

    Like setup, its first update fetches Google's list, which gives these devices.
    """
    client, _ = make_client(*addresses, session=network.session)
    client.google_devices = []
    client.google_devices_fetched = False
    return client


def poll(
    client: GlocaltokensApiClient, clock: Mock, seconds: int
) -> list[GoogleHomeDevice]:
    """Run the scheduled update at this time, and return its devices."""
    clock.return_value = seconds
    return asyncio.run(client.update_google_devices_information())


def entities(
    client: GlocaltokensApiClient, coordinator: Mock, device_id: str
) -> dict[str, GoogleHomeBaseEntity]:
    """Return the six entities of the device with this ID, by label."""
    return {
        entity.label: entity
        for entity in (
            entity_class(coordinator, client, device_id, device_id, None)
            for entity_class in FEATURES + ALWAYS
        )
    }


def available(by_label: dict[str, GoogleHomeBaseEntity]) -> set[str]:
    """Return the labels of the available entities."""
    return {label for label, entity in by_label.items() if entity.available}


def test_stop_asking_device_without_alarms(clock: Mock) -> None:
    """Stop asking a device for alarms, timers and settings once it shows it has none.

    A Chromecast Audio answers "not found" to these requests, and being asked on
    every update slows it down. A device that is starting answers "not found" for
    a while too, so its alarms must still answer so 10 minutes later, and its info
    must show no Google Assistant. From then on it's asked only for its info, which
    shows whether it answers. Other devices are asked as before.
    """
    client, glocaltokens, network = setup(NO_ALARMS, SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)))
    assert network.asked(SPEAKER) == WITH_INFO
    assert network.asked(OTHER) == EVERYTHING
    add_features, features_added = add_entities(coordinator, *FEATURES)
    _, always_added = add_entities(coordinator, *ALWAYS, needs_answer=False)
    assert {device_id for device_id, _ in features_added()} == {"device1"}
    assert sorted(always_added()) == [
        ("device0", "device"),
        ("device0", "reboot"),
        ("device1", "device"),
        ("device1", "reboot"),
    ]

    # Before 10 minutes, it may be starting
    for seconds in (at(3), at(9, 59)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == WITH_INFO
        assert network.asked(OTHER) == EVERYTHING

    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert network.asked(OTHER) == EVERYTHING

    # Its answer to a reboot doesn't add the entities it has no use for
    [chromecast, _] = client.google_devices
    asyncio.run(client.reboot_google_device(chromecast))
    assert network.asked(SPEAKER) == [REBOOT]
    assert chromecast.available
    poll(client, clock, at(13))
    add_features()
    assert features_added() == []
    assert network.asked(SPEAKER) == [INFO]

    poll(client, clock, at(19, 59))
    assert network.asked(SPEAKER) == [INFO]
    # Google's list is fetched again, with the same token
    poll(client, clock, at(20))
    assert glocaltokens.get_google_devices.call_count == 1
    assert network.asked(SPEAKER) == [INFO]
    # At 13, 19:59 and 20 minutes
    assert network.asked(OTHER) == EVERYTHING * 3


def test_keep_asking_starting_speaker(clock: Mock) -> None:
    """Keep asking a speaker whose alarms answer "not found" while it starts.

    In the order seen on a restarting Home Mini: "not found", then its old token
    rejected, then its alarms with the new token, 40 seconds after the first "not
    found". That answer starts the 10 minutes over, so a "not found" 10 minutes
    after the first one is a new first one, and it isn't checked for Google
    Assistant then: its info, which would show none, doesn't mark it.
    """
    client, glocaltokens, network = setup(
        dict.fromkeys([*EVERYTHING, INFO], HTTPStatus.NOT_FOUND)
    )
    [mini] = client.google_devices
    coordinator = Mock(data=poll(client, clock, at(0)))
    assert network.asked(SPEAKER) == WITH_INFO
    add_features, features_added = add_entities(coordinator, *FEATURES)
    assert features_added() == []

    # It rejects its old token, and Google's list, fetched straight away, still
    # gives that token
    network.replies[SPEAKER] = {
        **dict.fromkeys(EVERYTHING, HTTPStatus.UNAUTHORIZED),
        INFO: info(assistant_supported=True),
    }
    glocaltokens.get_google_devices.return_value = [
        found("device0", SPEAKER, OLD_TOKEN)
    ]
    poll(client, clock, at(0, 28))
    assert network.asked(SPEAKER) == WITH_INFO
    assert glocaltokens.get_google_devices.call_count == 1
    add_features()
    assert features_added() == []

    # The next update fetches the list again, which gives the new token
    network.replies[SPEAKER] = dict(SUPPORTED)
    glocaltokens.get_google_devices.return_value = [found("device0", SPEAKER)]
    coordinator.data = poll(client, clock, at(0, 40))
    assert glocaltokens.get_google_devices.call_count == 2
    assert network.asked(SPEAKER) == EVERYTHING
    assert [alarm.alarm_id for alarm in mini.get_sorted_alarms()] == [ALARM_ID]
    add_features()
    assert {label for _, label in features_added()} == FEATURE_LABELS

    # A later "not found" starts the 10 minutes over
    network.replies[SPEAKER] |= {ALARMS: HTTPStatus.NOT_FOUND, INFO: info()}
    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == WITH_INFO
    assert not mini.alarms_unsupported


@pytest.mark.parametrize(
    ("reply", "suppressed"),
    [
        pytest.param(info(), True, id="assistant-missing"),
        pytest.param(info(assistant_supported=False), True, id="assistant-false"),
        pytest.param(info(assistant_supported=True), False, id="assistant-true"),
        pytest.param(info(assistant_supported=None), False, id="assistant-null"),
        pytest.param(info(assistant_supported=0), False, id="assistant-0"),
        pytest.param(info(assistant_supported="false"), False, id="assistant-string"),
        pytest.param(
            (HTTPStatus.OK, {"name": "Speaker", "uptime": 46.5}),
            False,
            id="no-features",
        ),
        pytest.param(
            (HTTPStatus.OK, {"device_info": {"capabilities": {}}}),
            False,
            id="no-features-listed",
        ),
        # A body that would count with a 200
        pytest.param(
            (HTTPStatus.INTERNAL_SERVER_ERROR, info()[1]), False, id="http-500"
        ),
        # An error page
        pytest.param(
            (HTTPStatus.OK, ContentTypeError(Mock(), ())), False, id="not-json"
        ),
        pytest.param(
            (HTTPStatus.OK, JSONDecodeError("Expecting value", "<html>", 0)),
            False,
            id="invalid-json",
        ),
        pytest.param((HTTPStatus.OK, ["Speaker"]), False, id="not-an-object"),
    ],
)
def test_suppress_only_when_info_shows_no_assistant(
    clock: Mock, reply: Reply, suppressed: bool
) -> None:
    """Treat a device as having no alarms only when its info lists its features without Google Assistant.

    Any other reply says nothing either way, so the device is still asked as usual.
    """
    client, _, network = setup(NO_ALARMS)
    poll(client, clock, at(0))
    assert network.asked(SPEAKER) == WITH_INFO

    network.replies[SPEAKER][INFO] = reply
    poll(client, clock, at(10))

    assert client.google_devices[0].alarms_unsupported is suppressed
    assert network.asked(SPEAKER) == (
        [ALARMS, INFO] if suppressed else [ALARMS, INFO, VOLUME, DND]
    )


@pytest.mark.parametrize(
    ("first", "first_asked", "second", "suppressed"),
    [
        pytest.param(
            info(assistant_supported=True),
            [ALARMS, INFO, VOLUME, DND],
            info(assistant_supported=True),
            False,
            id="assistant",
        ),
        # A device that doesn't answer isn't asked the rest of that update
        pytest.param(
            TimeoutError(), [ALARMS, INFO], info(), True, id="no-answer-first"
        ),
    ],
)
def test_check_for_assistant_at_most_every_10_minutes(
    clock: Mock,
    first: Reply,
    first_asked: list[str],
    second: Reply,
    suppressed: bool,
) -> None:
    """Check a device whose alarms keep answering "not found" for Google Assistant at most every 10 minutes.

    Each update still asks for its info once, for the available attribute of its
    device sensor; the check uses that request when it's due. A device that reports
    Google Assistant but has no alarms, such as possibly a TV box, is otherwise
    asked as usual, and never treated as having no alarms.
    """
    client, _, network = setup(NO_ALARMS | {INFO: first})
    [device] = client.google_devices

    for seconds in (at(0), at(9, 59)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == WITH_INFO
    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == first_asked
    network.replies[SPEAKER][INFO] = second
    poll(client, clock, at(19, 59))
    assert network.asked(SPEAKER) == WITH_INFO
    assert not device.alarms_unsupported

    poll(client, clock, at(20))

    assert network.asked(SPEAKER) == (
        [ALARMS, INFO] if suppressed else [ALARMS, INFO, VOLUME, DND]
    )
    assert device.alarms_unsupported is suppressed


def test_keep_asking_while_device_doesnt_answer(clock: Mock) -> None:
    """Keep asking a device for its alarms while it doesn't answer, however long that lasts.

    A Chromecast Audio took 11 to 16 minutes to answer again after restarting.
    Only "not found" counts, so the 10 minutes start once it answers.
    """
    client, glocaltokens, network = setup(dict.fromkeys(NO_ALARMS, TimeoutError()))
    for seconds in range(at(0), at(15) + 1, at(3)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == [ALARMS, INFO]

    network.replies[SPEAKER] = dict(NO_ALARMS)
    for seconds in (at(18), at(21), at(24), at(27)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == WITH_INFO
    # Google's list was fetched again at 21 minutes, with the same token
    assert glocaltokens.get_google_devices.call_count == 1

    poll(client, clock, at(30))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported


@pytest.mark.parametrize(
    ("alarms", "seconds"),
    [
        # An answer counts at any time
        pytest.param((HTTPStatus.OK, {"alarm": [], "timer": []}), at(3), id="200"),
        # No answer counts only once the 10 minutes are up
        pytest.param(TimeoutError(), at(10), id="timeout"),
        pytest.param(HTTPStatus.UNAUTHORIZED, at(10), id="401"),
    ],
)
def test_start_over_when_alarms_answer(
    clock: Mock, alarms: Reply, seconds: int
) -> None:
    """Start the 10 minutes over when a device's alarms answer, or don't answer when they're up.

    It isn't checked for Google Assistant then, and the next "not found" starts the
    10 minutes. Its info shows no Google Assistant, so a check would mark it.
    """
    client, _, network = setup(NO_ALARMS)
    [device] = client.google_devices
    poll(client, clock, at(0))
    network.replies[SPEAKER][ALARMS] = alarms
    poll(client, clock, seconds)
    assert not device.alarms_unsupported

    network.replies[SPEAKER][ALARMS] = HTTPStatus.NOT_FOUND
    poll(client, clock, at(13))
    poll(client, clock, at(22, 59))
    assert not device.alarms_unsupported
    network.asked(SPEAKER)
    poll(client, clock, at(23))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert device.alarms_unsupported


@pytest.mark.parametrize(
    "alarms",
    [
        pytest.param(TimeoutError(), id="timeout"),
        pytest.param(HTTPStatus.UNAUTHORIZED, id="401"),
    ],
)
def test_keep_waiting_while_alarms_dont_answer(clock: Mock, alarms: Reply) -> None:
    """Keep the 10 minutes going when a device's alarms don't answer before they're up.

    A device that doesn't answer for a moment hasn't shown that it has alarms.
    """
    client, _, network = setup(dict(NO_ALARMS))
    poll(client, clock, at(0))
    network.replies[SPEAKER][ALARMS] = alarms
    poll(client, clock, at(3))
    network.asked(SPEAKER)

    network.replies[SPEAKER][ALARMS] = HTTPStatus.NOT_FOUND
    poll(client, clock, at(10))

    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported


def test_action_doesnt_start_check(clock: Mock) -> None:
    """Don't count a "not found" answer to an action that reads the alarms before an update.

    Only scheduled updates decide whether a device has alarms, so the update 10
    minutes later is the first "not found".
    """
    client, _, network = setup(NO_ALARMS)
    [device] = client.google_devices

    with pytest.raises(AlarmsAndTimersNotFetched):
        asyncio.run(client.update_alarms_and_timers(device, polling=False))
    assert network.asked(SPEAKER) == [ALARMS]

    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == WITH_INFO
    poll(client, clock, at(20))
    assert network.asked(SPEAKER) == [ALARMS, INFO]


def test_dont_ask_again_until_reload(clock: Mock) -> None:
    """Don't ask a device without alarms for them again until the integration is reloaded, whatever happens.

    Not when Google gives it a new token, and not when it would answer: support
    that a firmware update adds shows only after a reload. Until then, its alarms,
    timers and settings stay unavailable. Meanwhile it's asked only for its info.
    """
    client, glocaltokens, network = setup(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)), last_update_success=True)
    speaker = entities(client, coordinator, "device0")
    assert available(speaker) == FEATURE_LABELS | ALWAYS_LABELS
    assert network.asked(SPEAKER) == EVERYTHING

    network.replies[SPEAKER] = dict(NO_ALARMS)
    poll(client, clock, at(3))
    poll(client, clock, at(13))
    assert network.asked(SPEAKER) == [*WITH_INFO, ALARMS, INFO]
    assert available(speaker) == ALWAYS_LABELS

    network.replies[SPEAKER] = dict(SUPPORTED)
    for seconds in range(at(20), 2 * HOUR, at(10)):
        token = NEW_TOKEN if seconds < at(40) else NEWER_TOKEN
        glocaltokens.get_google_devices.return_value = [
            found("device0", SPEAKER, token)
        ]
        coordinator.data = poll(client, clock, seconds)
        assert network.asked(SPEAKER) == [INFO]
    # Fetched at 20, 40, 60, 80 and 100 minutes
    assert glocaltokens.get_google_devices.call_count == 5
    assert client.google_devices[0].auth_token == NEWER_TOKEN
    assert available(speaker) == ALWAYS_LABELS

    client = reload(network, SPEAKER)
    coordinator = Mock(data=poll(client, clock, 2 * HOUR), last_update_success=True)
    assert network.asked(SPEAKER) == EVERYTHING
    [device] = client.google_devices
    assert [alarm.alarm_id for alarm in device.get_sorted_alarms()] == [ALARM_ID]
    _, features_added = add_entities(coordinator, *FEATURES)
    assert {label for _, label in features_added()} == FEATURE_LABELS
    assert available(entities(client, coordinator, "device0")) == (
        FEATURE_LABELS | ALWAYS_LABELS
    )


def test_reload_checks_again(clock: Mock) -> None:
    """Check a device again after a reload, waiting the 10 minutes again, as it may be starting."""
    client, _, network = setup(NO_ALARMS)
    poll(client, clock, at(0))
    poll(client, clock, at(10))
    assert network.asked(SPEAKER) == [*WITH_INFO, ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported

    client = reload(network, SPEAKER)
    for seconds in (at(30), at(33), at(39, 59)):
        poll(client, clock, seconds)
        assert network.asked(SPEAKER) == WITH_INFO
    poll(client, clock, at(40))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported


def test_dont_ask_again_when_google_lists_device_again(clock: Mock) -> None:
    """Don't ask a device without alarms for them again when Google's list drops it and later lists it again.

    Only a reload does that; meanwhile it's asked only for its info. A device that
    Google lists for the first time is asked as usual.
    """
    client, glocaltokens, network = setup(SUPPORTED)
    network.replies[OTHER] = dict(SUPPORTED)
    coordinator = Mock(data=poll(client, clock, at(0)), last_update_success=True)
    add_features, features_added = add_entities(coordinator, *FEATURES)
    add_always, always_added = add_entities(coordinator, *ALWAYS, needs_answer=False)
    assert {label for _, label in features_added()} == FEATURE_LABELS
    always_added()
    speaker = entities(client, coordinator, "device0")
    network.replies[SPEAKER] = dict(NO_ALARMS)
    poll(client, clock, at(3))
    coordinator.data = poll(client, clock, at(13))
    assert network.asked(SPEAKER) == [*EVERYTHING, *WITH_INFO, ALARMS, INFO]

    glocaltokens.get_google_devices.return_value = []
    for seconds in (at(20), at(30)):
        coordinator.data = poll(client, clock, seconds)
        assert coordinator.data == []
        assert network.asked(SPEAKER) == []
    assert available(speaker) == set()

    # It comes back with a new token, with a device Google didn't list before
    glocaltokens.get_google_devices.return_value = [
        found("device0", SPEAKER, NEW_TOKEN),
        found("device1", OTHER),
    ]
    for seconds in (at(40), at(50)):
        coordinator.data = poll(client, clock, seconds)
        assert network.asked(SPEAKER) == [INFO]
    assert network.asked(OTHER) == EVERYTHING * 2
    assert available(speaker) == ALWAYS_LABELS
    add_features()
    add_always()
    assert sorted(features_added()) == sorted(
        ("device1", label) for label in FEATURE_LABELS
    )
    assert sorted(always_added()) == [("device1", "device"), ("device1", "reboot")]

    # Reloading checks it again, after the 10 minutes
    client = reload(network, SPEAKER, OTHER)
    coordinator = Mock(data=poll(client, clock, at(60)), last_update_success=True)
    assert network.asked(SPEAKER) == WITH_INFO
    add_features, features_added = add_entities(coordinator, *FEATURES)
    assert {device_id for device_id, _ in features_added()} == {"device1"}
    poll(client, clock, at(69, 59))
    assert network.asked(SPEAKER) == WITH_INFO
    poll(client, clock, at(70))
    assert network.asked(SPEAKER) == [ALARMS, INFO]
    assert client.google_devices[0].alarms_unsupported
    add_features()
    assert features_added() == []
