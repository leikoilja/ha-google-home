"""Tests for logging failed fetches of Google's device list."""

import asyncio
import contextlib
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


def test_log_sign_in_rejected_after_setup(
    clock: Mock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token once setup is done.

    Only setup leaves that to Home Assistant: later it asks to sign in again
    without saying why.
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


def test_log_sign_in_rejected_after_failed_update(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log why Google rejects the master token after setup, even without devices.

    The update then fails, but after an update that failed because Google couldn't
    be reached, Home Assistant doesn't log that it failed again, so the integration
    does, with Google's reason.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    entry = Mock()
    glocaltokens.get_google_devices.side_effect = ClientConnectionError
    with pytest.raises(ClientConnectionError):
        update_entry(client, entry)

    glocaltokens.get_google_devices.side_effect = rejected()
    clock.return_value = MINUTE
    with pytest.raises(ConfigEntryAuthFailed):
        update_entry(client, entry)

    # Without devices, Home Assistant doesn't update again until then
    later = "sign in again to fetch it"
    assert ("ERROR", f"Failed to fetch Google's device list ({later}): {REJECTED}") in (
        logged(caplog)
    )


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


def test_log_failed_fetch_again_when_it_fails_differently(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log a failed fetch as an error again when the one before failed another way.

    Such as when Google's sign-in, after being unavailable, rejects the master token,
    or answers again after it couldn't be reached. Any error status from Google is
    one way to fail, so an outage that alternates between them logs once. The next
    try is 1, 2, 5, 10 and then 20 minutes after each.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.google_home")
    # A device rejected its token, so the list is unknown
    client, glocaltokens = make_client("10.0.0.2")
    client.google_devices_fetched = False
    unavailable = answered(HTTPStatus.SERVICE_UNAVAILABLE)
    no_home_graph = HomegraphError(grpc.StatusCode.UNAVAILABLE, "Unavailable.")
    glocaltokens.get_google_devices.side_effect = [
        unavailable,
        rejected(),
        rejected(),
        no_home_graph,
        unavailable,
        too_many := answered(HTTPStatus.TOO_MANY_REQUESTS),
        ClientConnectionError(),
        too_many,
    ]
    for minutes in (*RETRY_MINUTES, 78):
        clock.return_value = minutes * MINUTE
        # Home Assistant logs the update that fails as Google can't be reached
        with contextlib.suppress(ClientConnectionError):
            update(client)

    assert glocaltokens.get_google_devices.call_count == 8
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        failure_logged(unavailable, 1),
        failure_logged(REJECTED, 2),
        failure_logged(no_home_graph, 10),
        failure_logged(unavailable, 20),
        failure_logged(too_many, 20),
    ]


def test_dont_log_recovery_after_google_couldnt_be_reached(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Log nothing when a fetch works after fetches that couldn't reach Google.

    The integration didn't log those as errors: Home Assistant logs that the update
    failed, and that it recovered.
    """
    client, glocaltokens = make_client()
    client.google_devices_fetched = False
    glocaltokens.get_google_devices.side_effect = [
        ClientConnectionError(),
        TimeoutError(),
        [],
    ]
    for minutes in RETRY_MINUTES[:3]:
        clock.return_value = minutes * MINUTE
        with contextlib.suppress(ClientConnectionError, TimeoutError):
            update(client)

    assert glocaltokens.get_google_devices.call_count == 3
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == []


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

    later = f"next try at {when}; further failures like this are logged at debug level"
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == [
        ("ERROR", f"Failed to fetch Google's device list ({later}): {unavailable}")
    ]
