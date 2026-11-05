"""Tests for logging failed fetches of Google's device list."""

import asyncio
from http import HTTPStatus
import logging
from pathlib import Path
from unittest.mock import Mock

from aiohttp import ClientConnectionError
from glocaltokens.exceptions import HomegraphError
import grpc  # type: ignore[import-untyped]
import pytest

from custom_components.google_home.const import FETCH_DEVICES_INTERVAL

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.exceptions import ConfigEntryAuthFailed

from .test_missing_devices import (
    FETCH_ERRORS,
    HASS,
    MINUTE,
    NOT_REJECTED,
    REJECTED,
    RETRY_MINUTES,
    answered,
    failure_logged,
    found,
    logged,
    make_client,
    rejected,
    set_up,
    update,
    update_entry,
    update_round,
)


def test_setup_leaves_rejected_master_token_to_home_assistant(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Fail setup with Google's reason when it rejects the master token, and log it only for debugging.

    Home Assistant logs why setup fails as a warning, with that reason, so an error
    from the integration would say the same thing twice.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")

    async def run() -> None:
        async with set_up(tmp_path, Mock(side_effect=rejected())):
            pass

    with pytest.raises(ConfigEntryAuthFailed) as err:
        asyncio.run(run())

    # Home Assistant logs the English text after "could not authenticate: ", with
    # Google's reason (test_setup.py checks the text, which needs the translations)
    assert err.value.translation_key == "sign_in_rejected"
    assert err.value.translation_placeholders == {"reason": "BadAuthentication"}
    lines = logged(caplog)
    assert ("DEBUG", f"Failed to fetch Google's device list: {REJECTED}") in lines
    assert [line for line in lines if line[0] not in {"DEBUG", "INFO"}] == []


@pytest.mark.parametrize("error", NOT_REJECTED)
def test_setup_logs_other_fetch_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """Log why Google's list can't be fetched at setup for another reason, as setup goes on without devices.

    Home Assistant logs nothing then.
    """

    async def run() -> None:
        async with set_up(tmp_path, Mock(side_effect=error)):
            pass

    asyncio.run(run())

    # The next update after the backoff tries again
    assert failure_logged(error, 1) in logged(caplog)


@pytest.mark.parametrize("error", NOT_REJECTED)
def test_setup_without_polling_says_to_reload(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """Say to reload when setup goes on without devices while polling is off.

    Home Assistant then schedules no update of the account, and without devices
    nothing asks for one, so the list isn't fetched again until a reload.
    """

    async def run() -> None:
        async with set_up(tmp_path, Mock(side_effect=error), polling_off=True):
            pass

    asyncio.run(run())

    later = "polling is off, so reload the integration to fetch it"
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        ("ERROR", f"Failed to fetch Google's device list ({later}): {error}")
    ]


def test_polling_off_with_devices_says_when_fetched_again(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Still say when the list is fetched again while polling is off and there are devices.

    Refreshing a device, such as with Refresh devices, asks for the account's update
    that fetches it.
    """
    client, glocaltokens = make_client("10.0.0.2")
    client.polling_off = True
    unavailable = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    glocaltokens.get_google_devices.side_effect = unavailable
    # The scheduled fetch is due
    clock.return_value = FETCH_DEVICES_INTERVAL
    update(client)

    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        failure_logged(unavailable, 20)
    ]


def test_log_sign_in_rejected_after_setup(
    clock: Mock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token once setup is done.

    Only setup's own fetch leaves that to Home Assistant: later it asks to sign in
    again without saying why.
    """
    # A device without an address, which no update asks
    google = Mock(return_value=[found("device0", None)])

    async def run() -> None:
        async with set_up(tmp_path, google) as (_, entry):
            client = entry.runtime_data.client
            google.side_effect = rejected()
            # The scheduled fetch is due
            clock.return_value = FETCH_DEVICES_INTERVAL
            await update_round(client)

    asyncio.run(run())

    assert google.call_count == 2
    # The list stays known, so the next scheduled fetch tries again
    assert failure_logged(REJECTED, 20) in logged(caplog)


def test_log_sign_in_rejected_after_setup_without_devices(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token after a setup that went on without devices.

    The update then fails, and Home Assistant doesn't update the account again until
    signing in again reloads the integration, so the error says to sign in again.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = rejected()
    clock.return_value = MINUTE
    with pytest.raises(ConfigEntryAuthFailed):
        update_entry(client, Mock())

    later = "sign in again to fetch it"
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        ("ERROR", f"Failed to fetch Google's device list ({later}): {REJECTED}")
    ]


def test_ask_to_sign_in_when_rejected_during_outage(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Fail the update when Google rejects the master token during an outage, without devices.

    Home Assistant then logs that authentication failed and asks to sign in again,
    as the integration logged only the outage's first failure as an error.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    entry = Mock()
    glocaltokens.get_google_devices.side_effect = ClientConnectionError()
    assert not update_entry(client, entry)

    glocaltokens.get_google_devices.side_effect = rejected()
    clock.return_value = MINUTE
    with pytest.raises(ConfigEntryAuthFailed) as err:
        update_entry(client, entry)

    assert err.value.translation_key == "sign_in_rejected"
    assert err.value.translation_placeholders == {"reason": "BadAuthentication"}
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        failure_logged("ClientConnectionError", 1)
    ]


def test_keep_list_when_scheduled_fetch_during_setup_fails(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep the list when a fetch that is due while setup still runs can't reach Google, and log it once.

    Only setup's own fetch fails setup. An update of the account while setup still
    asks the devices, such as for a device that mDNS found, fetches on schedule and
    keeps the list it has, so Home Assistant doesn't log that the update failed.
    """
    client, glocaltokens = make_client("10.0.0.2")
    devices = list(client.google_devices)
    client.setting_up = True
    glocaltokens.get_google_devices.side_effect = ClientConnectionError()
    clock.return_value = FETCH_DEVICES_INTERVAL

    assert list(update(client).values()) == devices
    assert glocaltokens.get_google_devices.call_count == 1
    assert client.google_devices_fetched
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        failure_logged("ClientConnectionError", 20)
    ]


def test_log_sign_in_rejected_at_scheduled_fetch_during_setup(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token at a fetch that is due while setup still runs, once.

    Only setup's own fetch leaves that to Home Assistant. A scheduled fetch, such as
    for a device that mDNS found, keeps the list, so the update goes on and Home
    Assistant only asks to sign in again, without saying why.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    client, glocaltokens = make_client("10.0.0.2")
    devices = list(client.google_devices)
    client.setting_up = True
    entry = Mock()
    glocaltokens.get_google_devices.side_effect = rejected()
    # The scheduled fetch is due
    clock.return_value = 20 * MINUTE
    assert list(update_entry(client, entry).values()) == devices

    assert client.google_devices_fetched
    assert client.sign_in_error is not None
    entry.async_start_reauth.assert_called_with(HASS)
    errors = [failure_logged(REJECTED, 20)]
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == errors

    # Once setup is done, Google rejects the next scheduled fetch too
    client.setting_up = False
    clock.return_value = 40 * MINUTE
    update_entry(client, entry)

    assert glocaltokens.get_google_devices.call_count == 2
    lines = logged(caplog)
    assert [line for line in lines if line[0] != "DEBUG"] == errors
    failed = ("DEBUG", f"Failed to fetch Google's device list: {REJECTED}")
    assert lines.count(failed) == 1


@pytest.mark.parametrize("error", FETCH_ERRORS)
def test_log_failed_fetches_once_until_one_works(
    clock: Mock, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """Log the first of failed fetches in a row as an error, the others for debugging, and when a fetch works again.

    During a long outage, the log then shows one error that says when the next try
    is, rather than one for each try. A failure after a fetch works is logged again.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    # A device rejected its token, so the list is unknown, and Google keeps it
    client, glocaltokens = make_client("10.0.0.2")
    client.google_devices_fetched = False
    listed = glocaltokens.get_google_devices.return_value
    # The next three fetches fail, the fourth and the scheduled fetch 20 minutes after
    # it work, and the next scheduled fetch fails
    glocaltokens.get_google_devices.side_effect = [
        error,
        error,
        error,
        listed,
        listed,
        error,
    ]
    for minutes in (0, 1, 3, 8, 28, 48):
        clock.return_value = minutes * MINUTE
        update(client)

    assert glocaltokens.get_google_devices.call_count == 6
    lines = logged(caplog)
    assert [line for line in lines if line[0] != "DEBUG"] == [
        failure_logged(error, 1),
        ("INFO", "Fetching Google's device list works again"),
        failure_logged(error, 20),
    ]
    failed = ("DEBUG", f"Failed to fetch Google's device list: {error}")
    assert lines.count(failed) == 2


def test_log_outage_once_however_fetches_fail(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log only the first failed fetch of an outage as an error, however the others fail, and when a fetch works again.

    Such as when Google's sign-in is busy, then rejects the master token, the home
    graph can't be fetched, or Google can't be reached, whichever request fails.
    The tries are 1, 2, 5, 10 and then 20 minutes apart, and the error says when the
    first of them is. The others are logged for debugging, with their reason.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    # The list is unknown, as after a device rejected its token
    client, glocaltokens = make_client("10.0.0.2")
    client.google_devices_fetched = False
    unavailable = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    no_home_graph = HomegraphError(grpc.StatusCode.UNAVAILABLE, "Unavailable.")
    too_many = answered(HTTPStatus.TOO_MANY_REQUESTS)
    deadline = HomegraphError(grpc.StatusCode.DEADLINE_EXCEEDED, "Deadline Exceeded")
    glocaltokens.get_google_devices.side_effect = [
        unavailable,
        rejected(),
        no_home_graph,
        too_many,
        ClientConnectionError(),
        TimeoutError(),
        deadline,
        [],
    ]
    for minutes in (*RETRY_MINUTES, 78):
        clock.return_value = minutes * MINUTE
        update(client)

    assert glocaltokens.get_google_devices.call_count == 8
    lines = logged(caplog)
    assert [line for line in lines if line[0] != "DEBUG"] == [
        failure_logged(unavailable, 1),
        ("INFO", "Fetching Google's device list works again"),
    ]
    failed = "Failed to fetch Google's device list: "
    # An error that Google's sign-in can't be reached or doesn't answer in time may
    # have no message, so its type is the reason
    assert [line for line in lines if line[1].startswith(failed)] == [
        ("DEBUG", failed + reason)
        for reason in (
            REJECTED,
            str(no_home_graph),
            str(too_many),
            "ClientConnectionError",
            "TimeoutError",
            str(deadline),
        )
    ]


def test_log_scheduled_fetch_outage_once_across_a_timeout(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log an outage of scheduled fetches once, although a timeout comes between two fetches that get 503.

    The list is known, so the fetches are 20 minutes apart and keep it. Only the
    first 503 is an error; the timeout and the second 503 are logged for debugging,
    and the fourth fetch, which works, once at info level.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    client, glocaltokens = make_client("10.0.0.2")
    listed = glocaltokens.get_google_devices.return_value
    unavailable = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    glocaltokens.get_google_devices.side_effect = [
        unavailable,
        TimeoutError(),
        unavailable,
        listed,
    ]
    for minutes in (20, 40, 60, 80):
        clock.return_value = minutes * MINUTE
        update(client)

    assert glocaltokens.get_google_devices.call_count == 4
    lines = logged(caplog)
    assert [line for line in lines if line[0] != "DEBUG"] == [
        failure_logged(unavailable, 20),
        ("INFO", "Fetching Google's device list works again"),
    ]
    failed = "Failed to fetch Google's device list: "
    assert [line for line in lines if line[1].startswith(failed)] == [
        ("DEBUG", failed + "TimeoutError"),
        ("DEBUG", failed + str(unavailable)),
    ]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ClientConnectionError(), "ClientConnectionError"),
        (TimeoutError(), "TimeoutError"),
        (ClientConnectionError("Cannot connect to host"), "Cannot connect to host"),
    ],
    ids=["unreachable", "timed-out", "unreachable-with-message"],
)
def test_log_google_unreachable_once_after_setup(
    clock: Mock, caplog: pytest.LogCaptureFixture, error: Exception, reason: str
) -> None:
    """Log once when Google can't be reached after setup, also before any fetch has worked, and once when a fetch works again.

    The update keeps the devices rather than fail, so Home Assistant logs neither
    that it failed nor that it recovered. Each outage is logged: here the list is
    unknown until the third fetch works, and the fetch scheduled 20 minutes later
    fails again.
    """
    # Setup went on without devices
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = [error, TimeoutError(), [], error, []]
    for minutes in (0, 1, 3, 23, 43):
        clock.return_value = minutes * MINUTE
        assert update(client) == {}

    assert glocaltokens.get_google_devices.call_count == 5
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        failure_logged(reason, 1),
        ("INFO", "Fetching Google's device list works again"),
        failure_logged(reason, 20),
        ("INFO", "Fetching Google's device list works again"),
    ]


@pytest.mark.parametrize(
    ("fetched", "starts_at", "when"),
    [
        # The next scheduled fetch is due 20 minutes after this one started
        (True, FETCH_DEVICES_INTERVAL, "the first update after 17 min"),
        # The first wait after a failed fetch is 1 minute, which has passed
        (False, 0, "the next update"),
    ],
)
def test_log_next_try_from_when_fetch_fails(
    clock: Mock,
    caplog: pytest.LogCaptureFixture,
    fetched: bool,
    starts_at: int,
    when: str,
) -> None:
    """Say how long until the next try from when a fetch fails, as the wait starts with the fetch.

    Here Google answers with 503 after 3 minutes.
    """
    client, glocaltokens = make_client("10.0.0.2")
    client.google_devices_fetched = fetched
    unavailable = answered(HTTPStatus.SERVICE_UNAVAILABLE)

    def answer_late(*_args: object, **_options: object) -> None:
        clock.return_value = starts_at + 3 * MINUTE
        raise unavailable

    glocaltokens.get_google_devices.side_effect = answer_late
    clock.return_value = starts_at
    update(client)

    later = (
        f"next try at {when}; further failures are logged at debug level until a "
        "fetch works"
    )
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        ("ERROR", f"Failed to fetch Google's device list ({later}): {unavailable}")
    ]
