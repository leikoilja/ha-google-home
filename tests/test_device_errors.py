"""Tests for logging the errors of a device's requests once, until an update works."""

import asyncio
from http import HTTPStatus
import logging
import re
from unittest.mock import Mock

from aiohttp import ClientPayloadError, ServerDisconnectedError
import pytest

from custom_components.google_home.exceptions import AlarmsAndTimersNotFetched

from .test_unsupported_devices import (
    ALARMS,
    DND,
    INFO,
    NO_ALARMS,
    OTHER,
    SPEAKER,
    SUPPORTED,
    Reply,
    at,
    poll,
    setup,
)

SERVER_ERROR = HTTPStatus.INTERNAL_SERVER_ERROR
# What the errors of Device 0 say, with the request's answer left out
FAILED_500 = "Failed to access Device 0, API returned 500: <answer>"
DROPPED = "Request from Device 0 device error"
UNKNOWN_REPLY = (
    "Failed to parse fetched alarms and timers for device Device 0 - API returned "
    "unknown json structure. Received = {'alarms': []}"
)
WORKS_AGAIN = "Updating Device 0 works again"


def lines(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    """Return the level and message of each line the integration logged, with any answer shown as <answer>."""
    return [
        (
            record.levelname,
            re.sub(r"<MagicMock .*>", "<answer>", record.getMessage()),
        )
        for record in caplog.records
        if record.name == "custom_components.google_home"
    ]


def above_debug(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str]]:
    """Return the lines the integration logged at info level or above."""
    return [line for line in lines(caplog) if line[0] != "DEBUG"]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        pytest.param(SERVER_ERROR, FAILED_500, id="error-status"),
        pytest.param(ServerDisconnectedError(), DROPPED, id="dropped-connection"),
        pytest.param(
            (HTTPStatus.OK, ClientPayloadError("cut off")), DROPPED, id="cut-off"
        ),
        pytest.param(
            (HTTPStatus.OK, {"alarms": []}), UNKNOWN_REPLY, id="unknown-reply"
        ),
    ],
)
def test_log_failure_once_until_update_works(
    clock: Mock, caplog: pytest.LogCaptureFixture, failure: Reply, message: str
) -> None:
    """Log a failure of a device's alarms request as an error once, and for debugging until an update works.

    Then log that it works again, and a later failure as an error again. A dropped
    connection or a cut-off answer is logged with its traceback the first time.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    client, _, network = setup(SUPPORTED)
    times = iter(range(at(0), at(10), 15))
    network.replies[SPEAKER][ALARMS] = failure
    for _ in range(3):
        poll(client, clock, next(times))
    network.replies[SPEAKER][ALARMS] = SUPPORTED[ALARMS]
    poll(client, clock, next(times))
    network.replies[SPEAKER][ALARMS] = failure
    poll(client, clock, next(times))

    assert above_debug(caplog) == [
        ("ERROR", message),
        ("INFO", WORKS_AGAIN),
        ("ERROR", message),
    ]
    assert lines(caplog).count(("DEBUG", message)) == 2
    errors = [
        record
        for record in caplog.records
        if record.name == "custom_components.google_home"
        and record.levelname == "ERROR"
    ]
    assert [bool(record.exc_info) for record in errors] == [message == DROPPED] * 2


def test_log_each_type_of_failure_once(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log a new type of failure as an error, but not one that an earlier update already logged.

    Until an update works, also when the failures alternate.
    """
    client, _, network = setup(SUPPORTED)
    for seconds, failure in (
        (at(0), SERVER_ERROR),
        (at(0, 15), ServerDisconnectedError()),
        # Another type of failure with the same message: its own type counts
        (at(0, 30), (HTTPStatus.OK, ClientPayloadError("cut off"))),
        (at(0, 45), SERVER_ERROR),
        (at(1), HTTPStatus.SERVICE_UNAVAILABLE),
    ):
        network.replies[SPEAKER][ALARMS] = failure
        poll(client, clock, seconds)

    assert above_debug(caplog) == [
        ("ERROR", FAILED_500),
        ("ERROR", DROPPED),
        ("ERROR", DROPPED),
        ("ERROR", "Failed to access Device 0, API returned 503: <answer>"),
    ]


def test_log_failure_once_across_a_timeout(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log a failure once, although a timeout comes between two updates that get it, and log once that an update works again.

    A timeout is logged only for debugging and doesn't make the update work, so the
    second 500 is logged for debugging too.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    client, _, network = setup(SUPPORTED)
    for seconds, reply in (
        (at(0), SERVER_ERROR),
        (at(0, 15), TimeoutError()),
        (at(0, 30), SERVER_ERROR),
        (at(0, 45), SUPPORTED[ALARMS]),
    ):
        network.replies[SPEAKER][ALARMS] = reply
        poll(client, clock, seconds)

    assert above_debug(caplog) == [("ERROR", FAILED_500), ("INFO", WORKS_AGAIN)]
    assert lines(caplog).count(("DEBUG", FAILED_500)) == 1


def test_log_failures_of_each_device(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log the same failure of two devices once for each of them."""
    client, _, network = setup(SUPPORTED, SUPPORTED)
    network.replies[SPEAKER][ALARMS] = SERVER_ERROR
    network.replies[OTHER][ALARMS] = SERVER_ERROR
    for seconds in (at(0), at(0, 15)):
        poll(client, clock, seconds)

    assert above_debug(caplog) == [
        ("ERROR", FAILED_500),
        ("ERROR", FAILED_500.replace("Device 0", "Device 1")),
    ]


def test_update_with_a_failed_setting_doesnt_work(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log a setting that keeps failing once, although the device's alarms answer.

    An update works only once all its requests do, so no line says it works again.
    """
    client, _, network = setup(SUPPORTED)
    network.replies[SPEAKER][DND] = SERVER_ERROR
    for seconds in (at(0), at(0, 15), at(0, 30)):
        poll(client, clock, seconds)

    assert above_debug(caplog) == [("ERROR", FAILED_500)]


def test_device_without_alarms_works_again_when_its_info_answers(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log that a device found to have no alarms works again only once its info answers.

    Its alarms request fails, then it's found to have no alarms, and its info doesn't
    answer: none of these updates works. The update after that does.
    """
    client, _, network = setup(SUPPORTED)
    network.replies[SPEAKER][ALARMS] = ServerDisconnectedError()
    poll(client, clock, at(0))
    # Its alarms answer "not found" at two updates 10 minutes apart, and its info
    # shows no Google Assistant
    network.replies[SPEAKER] = dict(NO_ALARMS)
    poll(client, clock, at(0, 15))
    poll(client, clock, at(10, 15))
    [device] = client.google_devices
    assert device.alarms_unsupported
    network.replies[SPEAKER][INFO] = TimeoutError()
    poll(client, clock, at(10, 30))
    assert above_debug(caplog) == [("ERROR", DROPPED)]

    network.replies[SPEAKER][INFO] = NO_ALARMS[INFO]
    poll(client, clock, at(10, 45))
    poll(client, clock, at(11))

    assert above_debug(caplog) == [("ERROR", DROPPED), ("INFO", WORKS_AGAIN)]


def test_actions_log_every_failure_and_dont_end_updates_failing(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log every failure of an action, without changing what the device's updates log.

    An action's failure that an update already logged is still logged, and one that
    works doesn't mean the updates work again.
    """
    client, _, network = setup(SUPPORTED)
    [device] = client.google_devices
    network.replies[SPEAKER][ALARMS] = SERVER_ERROR
    poll(client, clock, at(0))
    with pytest.raises(AlarmsAndTimersNotFetched):
        asyncio.run(client.update_alarms_and_timers(device, polling=False))
    poll(client, clock, at(0, 15))
    network.replies[SPEAKER][ALARMS] = SUPPORTED[ALARMS]
    asyncio.run(client.update_alarms_and_timers(device, polling=False))
    network.replies[SPEAKER][ALARMS] = SERVER_ERROR
    poll(client, clock, at(0, 30))

    assert above_debug(caplog) == [("ERROR", FAILED_500)] * 2
