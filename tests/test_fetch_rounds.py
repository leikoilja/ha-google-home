"""Tests for fetching Google's list at most once per round under independent timers.

Each update of the account's list starts a round. The tests run the coordinators'
updates in an explicit order, with the client's clock set for each, rather than wait
for their timers. The speakers reject every token unless a test says otherwise.
"""

import asyncio
from unittest.mock import Mock

from glocaltokens.client import Device
import pytest
from pytest_homeassistant.common import MockConfigEntry
from requests.exceptions import ConnectionError as RequestsConnectionError

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable-next=wrong-import-order
from homeassistant.core import HomeAssistant

from .test_coordinators import BEDROOM, BEDROOM_ID, coordinators
from .test_missing_devices import LOCAL_AUTH_TOKEN, make_client, until
from .test_token_rejected import accepting
from .test_unsupported_devices import SPEAKER

# Labels for the coordinators' updates in a test
ACCOUNT = "account"
KITCHEN = "kitchen"
BOTH = "both speakers together"
KITCHEN_REFRESH = "refresh of the kitchen speaker"
# A token that Google never gives, so the speakers reject every token
NEVER = "never-given"


def recording(clock: Mock, glocaltokens: Mock) -> list[float]:
    """Return the times at which Google's list is fetched from now on."""
    times: list[float] = []
    devices: list[Device] = glocaltokens.get_google_devices.return_value

    def fetch(**_kwargs: object) -> list[Device]:
        times.append(float(clock.return_value))
        return devices

    glocaltokens.get_google_devices.side_effect = fetch
    return times


@pytest.mark.parametrize(
    ("steps", "fetched_at"),
    [
        pytest.param(
            [(0, ACCOUNT), (14, KITCHEN), (15, ACCOUNT), (29, KITCHEN), (30, ACCOUNT)],
            [14, 15, 30],
            id="speaker-before-account",
        ),
        pytest.param(
            [(0, ACCOUNT), (3, KITCHEN), (9, BEDROOM_ID), (15, ACCOUNT)],
            [3, 15],
            id="two-speakers",
        ),
        pytest.param(
            [(0, ACCOUNT), (3, BOTH), (15, ACCOUNT)], [3, 15], id="speakers-together"
        ),
        pytest.param(
            [(0, ACCOUNT), (2, KITCHEN), (10, KITCHEN_REFRESH), (15, ACCOUNT)],
            [2, 15],
            id="manual-refresh",
        ),
    ],
)
async def test_one_fetch_per_round(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    clock: Mock,
    steps: list[tuple[int, str]],
    fetched_at: list[int],
) -> None:
    """Fetch Google's list at most once from one update of the list to the next, whoever asks.

    The speakers reject every token, so the list stays unknown and each update of
    the list fetches it. A speaker's update fetches it only when nothing has since
    the update of the list started. A refresh of a speaker doesn't start a round.
    """
    google_answers = asyncio.Event()
    google_answers.set()
    session = accepting(NEVER)
    client, glocaltokens = make_client(
        SPEAKER, BEDROOM, session=session, google_answers_when=google_answers.is_set
    )
    times = recording(clock, glocaltokens)
    data = coordinators(hass, config_entry, client)

    for seconds, update in steps:
        clock.return_value = seconds
        if update == ACCOUNT:
            await data.account.async_refresh()
        elif update == BOTH:
            google_answers.clear()
            polls = [
                asyncio.create_task(coordinator.async_refresh())
                for coordinator in data.devices.values()
            ]
            # Both rejected their token: one fetches, the other waits for it
            await until(lambda: session.request.call_count == 2)
            google_answers.set()
            await asyncio.gather(*polls)
        elif update == KITCHEN_REFRESH:
            await data.devices["device0"].async_request_refresh()
        else:
            device_id = "device0" if update == KITCHEN else "device1"
            await data.devices[device_id].async_refresh()

    assert times == fetched_at
    # The refresh's cooldown
    await data.devices["device0"].async_shutdown()


async def test_one_fetch_per_round_across_speaker_update(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: Mock
) -> None:
    """Fetch once in each round when the list's update starts a new one during a speaker's update.

    The speaker's update starts at 14 seconds and fetches for its rejected token.
    The list's update at 15 seconds comes between its alarms and its alarm volume,
    and fetches the list, which is unknown. The speaker's later requests are in that
    round and don't fetch again.
    """
    requests = 0

    async def before_answer(_token: str) -> None:
        nonlocal requests
        requests += 1
        # Its alarms, again with the new token, and then its alarm volume
        if requests == 3:
            clock.return_value = 15
            await data.account.async_refresh()

    client, glocaltokens = make_client(SPEAKER, session=accepting(NEVER, before_answer))
    times = recording(clock, glocaltokens)
    data = coordinators(hass, config_entry, client)
    await data.account.async_refresh()

    clock.return_value = 14
    await data.devices["device0"].async_refresh()
    assert times == [14, 15]
    clock.return_value = 30
    await data.account.async_refresh()
    assert times == [14, 15, 30]


async def test_backoff_after_speaker_fetch_fails(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: Mock
) -> None:
    """Wait 1, 2, 5 and 10 minutes after a failed fetch that a speaker's update started.

    Google can't be reached from the speaker's first rejected token on. The speaker
    updates 14 seconds after each update of the list, so it's the first to fetch
    once each wait is over. The waits are written out, not taken from the constant.
    """
    client, glocaltokens = make_client(SPEAKER, session=accepting(NEVER))
    times: list[float] = []

    def unreachable(**_kwargs: object) -> list[Device]:
        times.append(float(clock.return_value))
        raise RequestsConnectionError

    glocaltokens.get_google_devices.side_effect = unreachable
    data = coordinators(hass, config_entry, client)

    for seconds in range(0, 500, 15):
        clock.return_value = seconds
        await data.account.async_refresh()
        clock.return_value = seconds + 14
        await data.devices["device0"].async_refresh()

    assert times == [14, 74, 194, 494]


async def test_schedule_after_speaker_fetch(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: Mock
) -> None:
    """Fetch Google's list on schedule at the first update of the list 20 minutes after a speaker's fetch."""
    client, glocaltokens = make_client(SPEAKER, session=accepting(LOCAL_AUTH_TOKEN))
    [kitchen] = client.google_devices
    kitchen.auth_token = LOCAL_AUTH_TOKEN
    times = recording(clock, glocaltokens)
    data = coordinators(hass, config_entry, client)

    for seconds in range(600, 1831, 15):
        clock.return_value = seconds
        await data.account.async_refresh()
        clock.return_value = seconds + 14
        if seconds == 600:
            # The speaker's token changes
            kitchen.auth_token = "token"
        await data.devices["device0"].async_refresh()

    assert times == [614, 1815]
