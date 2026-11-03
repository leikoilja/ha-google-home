"""Tests for how long a device that rejects the token Google gives waits before Google is asked again.

While polling, a device that rejects the token from a fetch of Google's list that
worked waits 1, 2, 5, 10 and then 20 minutes from the start of each such fetch
before its rejection fetches the list again, until it accepts a token.
"""

import asyncio
from http import HTTPStatus
import itertools
import logging
from unittest.mock import Mock

from glocaltokens.client import Device
import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.exceptions import DeviceRequestFailed

from .test_missing_devices import (
    HOUR,
    LOCAL_AUTH_TOKEN,
    MINUTE,
    RETRY_MINUTES,
    answered,
    fetch_times,
    found,
    logged,
    make_client,
    when_fetched,
)
from .test_token_rejected import NEWER_TOKEN, OLD_TOKEN, accepting, tokens_sent


def rejecting_and_answering(
    *, new_tokens: bool = False
) -> tuple[GlocaltokensApiClient, Mock, Mock]:
    """Return a client whose device at 10.0.0.2 rejects every token Google gives, and whose device at 10.0.0.3 accepts its own.

    Also return its fake glocaltokens and its session. Google gives the first device
    the token it already has, or with new_tokens a new one at each fetch.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", "10.0.0.3", session=session)
    client.google_devices[1].auth_token = LOCAL_AUTH_TOKEN
    fetches = itertools.count()

    def google(**_: object) -> list[Device]:
        token = f"{next(fetches):0>108}" if new_tokens else OLD_TOKEN
        return [found("device0", "10.0.0.2", token), found("device1", "10.0.0.3")]

    glocaltokens.get_google_devices.side_effect = google
    return client, glocaltokens, session


@pytest.mark.parametrize(
    "new_tokens", [False, True], ids=["same-token", "new-token-each-fetch"]
)
def test_fetch_less_often_for_device_rejecting_every_token(
    clock: Mock, new_tokens: bool
) -> None:
    """Ask Google less and less often for a device that rejects every token Google gives, however often the devices update.

    The device waits 1, 2, 5, 10 and then 20 minutes from the start of each fetch
    whose token it rejects: 7 fetches in the first hour, and 3 an hour after that,
    rather than one at each update. The list stays known, and the other device
    updates as usual meanwhile.
    """
    client, glocaltokens, session = rejecting_and_answering(new_tokens=new_tokens)
    kitchen, bedroom = client.google_devices

    first_hour = fetch_times(client, glocaltokens, clock, 15)
    second_hour = fetch_times(client, glocaltokens, clock, 15 + HOUR + 15)

    assert first_hour == [15 + minutes * MINUTE for minutes in RETRY_MINUTES]
    assert second_hour == [15 + minutes * MINUTE for minutes in (78, 98, 118)]
    assert client.google_devices_fetched
    assert (kitchen.available, bedroom.available) == (False, True)
    # Asked for its alarms, alarm volume and Do Not Disturb at each of the 241
    # updates of each hour
    assert tokens_sent(session, to="10.0.0.3") == [LOCAL_AUTH_TOKEN] * 3 * 2 * 241


def test_other_device_gets_new_token_while_device_waits(clock: Mock) -> None:
    """Fetch Google's list straight away for another device whose token changes while a device that rejects every token waits.

    The wait holds back only the fetches that the waiting device's rejections would
    start. Rejecting the token from that fetch doesn't make it wait longer.
    """
    client, glocaltokens, session = rejecting_and_answering()
    kitchen, bedroom = client.google_devices
    # The device rejects the token Google gives, and waits until 60 seconds
    assert when_fetched(client, glocaltokens, clock, [0]) == [0]

    # The other device restarts with a new token, which Google gives
    session.request.side_effect = accepting(NEWER_TOKEN).request.side_effect
    glocaltokens.get_google_devices.side_effect = None
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", OLD_TOKEN),
        found("device1", "10.0.0.3", NEWER_TOKEN),
    ]

    assert when_fetched(client, glocaltokens, clock, [15, 30, 45, 60]) == [15, 60]
    assert (kitchen.available, bedroom.available) == (False, True)


def test_wait_starts_over_once_device_accepts_token(clock: Mock) -> None:
    """Start a device's wait over once it accepts a token.

    After the next token from Google that it rejects, it waits 1 minute again, not
    the 5 that a third one in a row would.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", session=session)
    [kitchen] = client.google_devices
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", OLD_TOKEN)
    ]
    # It rejects the token Google gives at 0 and again 1 minute later
    assert when_fetched(client, glocaltokens, clock, [0, 15, 60, 75]) == [0, 60]

    # Google gives the token it accepts at its fetch 2 minutes after that
    glocaltokens.get_google_devices.return_value = [found("device0", "10.0.0.2")]
    assert when_fetched(client, glocaltokens, clock, [165, 180]) == [180]
    assert kitchen.available

    # It restarts with a new token, which Google doesn't have yet
    session.request.side_effect = accepting(NEWER_TOKEN).request.side_effect
    assert when_fetched(client, glocaltokens, clock, [195, 240, 255]) == [195, 255]


def test_device_waits_longer_only_after_another_fetch(clock: Mock) -> None:
    """Make a device wait longer only for a fetch that started once its wait was over, not one it already counted.

    Its update once the wait is over can come before the account's update starts a
    new round, in a round whose fetch it already counted. Rejecting that token
    again doesn't make it wait 2 minutes from that fetch, so the next round fetches.
    """
    client, glocaltokens = make_client("10.0.0.2", session=accepting(NEWER_TOKEN))
    [kitchen] = client.google_devices
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", OLD_TOKEN)
    ]
    assert when_fetched(client, glocaltokens, clock, [0]) == [0]

    # Its own update 1 minute later, before the account's
    clock.return_value = MINUTE
    asyncio.run(client.update_device(kitchen))
    assert glocaltokens.get_google_devices.call_count == 1

    assert when_fetched(client, glocaltokens, clock, [MINUTE + 15]) == [MINUTE + 15]


def test_fetch_during_wait_doesnt_make_device_wait_longer(clock: Mock) -> None:
    """Don't make a device wait longer for a fetch that started while it waited, such as another device's.

    Its update once the wait is over can come before the account's update starts a
    new round, in a round in which another device fetched the list during the wait.
    Rejecting the token from that fetch again doesn't make it wait 2 minutes from
    that fetch, so the next round fetches.
    """
    client, glocaltokens, session = rejecting_and_answering()
    kitchen, bedroom = client.google_devices
    # The device rejects the token Google gives, and waits until 60 seconds
    assert when_fetched(client, glocaltokens, clock, [0, 45]) == [0]

    # The other device restarts with a new token, which Google gives
    session.request.side_effect = accepting(NEWER_TOKEN).request.side_effect
    glocaltokens.get_google_devices.side_effect = None
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", OLD_TOKEN),
        found("device1", "10.0.0.3", NEWER_TOKEN),
    ]
    # Their own updates, in the round that started at 45 seconds
    for seconds, device in ((50, bedroom), (55, kitchen), (60, kitchen)):
        clock.return_value = seconds
        asyncio.run(client.update_device(device))
    assert glocaltokens.get_google_devices.call_count == 2
    assert bedroom.available

    assert when_fetched(client, glocaltokens, clock, [75]) == [75]


def test_action_waits_with_device(clock: Mock) -> None:
    """Fetch Google's list for an action on a device that rejects the token Google gives only once the device's wait is over.

    An update that waited didn't fetch the list, so an action after the wait fetches
    it without waiting for the next update.
    """
    client, glocaltokens = make_client("10.0.0.2", session=accepting(NEWER_TOKEN))
    [kitchen] = client.google_devices
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", OLD_TOKEN)
    ]
    assert when_fetched(client, glocaltokens, clock, [0, 15]) == [0]

    def turn_on_do_not_disturb_at(seconds: int) -> int:
        clock.return_value = seconds
        with pytest.raises(DeviceRequestFailed) as err:
            asyncio.run(client.set_do_not_disturb(kitchen, enable=True))
        assert err.value.reason == "token_rejected"
        return int(glocaltokens.get_google_devices.call_count)

    assert turn_on_do_not_disturb_at(MINUTE - 5) == 1
    assert turn_on_do_not_disturb_at(MINUTE + 5) == 2


def test_device_fetch_fails_once_wait_is_over(clock: Mock) -> None:
    """Wait as after any failed fetch when the fetch that a device starts after its wait fails.

    The list is then unknown until a fetch works, and the backoff after failed
    fetches holds back every fetch. Once Google answers again, the device rejects
    that token too and waits 2 minutes from that fetch: the failed one gave it no
    token, so it doesn't count.
    """
    client, glocaltokens = make_client("10.0.0.2", session=accepting(NEWER_TOKEN))
    glocaltokens.get_google_devices.return_value = [
        found("device0", "10.0.0.2", OLD_TOKEN)
    ]
    assert when_fetched(client, glocaltokens, clock, [15]) == [15]

    glocaltokens.get_google_devices.side_effect = answered(
        HTTPStatus.SERVICE_UNAVAILABLE
    )
    # Its fetch once its wait is over fails, and the next one waits 1 minute, then 2
    assert when_fetched(client, glocaltokens, clock, range(30, 136, 15)) == [75, 135]
    assert not client.google_devices_fetched

    glocaltokens.get_google_devices.side_effect = None
    assert when_fetched(client, glocaltokens, clock, range(150, 376, 15)) == [255, 375]
    assert client.google_devices_fetched


# What the log says when a device rejects the token from a fetch that worked, with
# the minutes until Google is asked again, and what its error adds
REJECTED_MESSAGE = (
    "device0 rejected the token that Google gave it. Google is asked for a new one "
    "at the first update after {} min"
)
REJECTED_ERROR = (
    f"{REJECTED_MESSAGE}; further rejections are logged at debug level until it "
    "accepts one"
)


@pytest.mark.parametrize(
    ("accepts_from", "fetched", "not_debug"),
    [
        # As right after it restarts, while Google still gives its old token
        pytest.param(MINUTE, [0, 60], [], id="accepts-next-token"),
        pytest.param(
            3 * MINUTE,
            [0, 60, 180],
            [
                ("ERROR", REJECTED_ERROR.format(2)),
                ("INFO", "Updating device0 works again"),
            ],
            id="rejects-next-token",
        ),
    ],
)
def test_log_device_rejecting_tokens_once(
    clock: Mock,
    caplog: pytest.LogCaptureFixture,
    accepts_from: int,
    fetched: list[int],
    not_debug: list[tuple[str, str]],
) -> None:
    """Log an error once a device has rejected the tokens from two fetches in a row, with when Google is asked again, and log when it works again.

    Right after a device restarts, Google may still give its old token for a short
    while, so rejecting the token from one fetch is logged for debugging only. So
    are the rejections after the error.
    """
    session = accepting(LOCAL_AUTH_TOKEN)
    client, glocaltokens = make_client("10.0.0.2", session=session)

    def google(**_: object) -> list[Device]:
        # Google gives the token the device accepts from this time on
        token = LOCAL_AUTH_TOKEN if clock.return_value >= accepts_from else OLD_TOKEN
        return [found("device0", "10.0.0.2", token)]

    glocaltokens.get_google_devices.side_effect = google
    caplog.set_level(logging.DEBUG)

    times = [0, 15, 60, 75, 180]
    assert when_fetched(client, glocaltokens, clock, times) == fetched
    assert [line for line in logged(caplog) if line[0] != "DEBUG"] == not_debug
    assert ("DEBUG", REJECTED_MESSAGE.format(1)) in logged(caplog)
    # After the error, its rejection at 75 seconds is logged with the error's wording
    assert (("DEBUG", REJECTED_ERROR.format(2)) in logged(caplog)) == bool(not_debug)
