"""Tests for Home Assistant starting together with the speakers, as after a power cut.

As in test_setup, the integration runs inside Home Assistant, and only glocaltokens,
mDNS and the speakers' answers are faked. Google lists the speakers without an
address, and mDNS reports each one later. The speakers update every 15 seconds,
and setup runs their first update.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
from glocaltokens.client import Device
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.google_home.const import SUPPORT_CHECK_DELAY

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .conftest import BEDROOM, SPEAKER_ID, SPEAKER_NAME, Replies
from .test_coordinators import STARTING, runtime
from .test_missing_devices import found
from .test_setup import set_up
from .test_unsupported_devices import NO_ALARMS, SPEAKER, SUPPORTED

# pylint: enable=wrong-import-order


class Shown(NamedTuple):
    """What an entity shows, if it's there."""

    state: str
    # Whether Home Assistant restored it from the registry
    restored: bool = False
    # How many alarms or timers the alarms or timers sensor lists, which it does only
    # while it's available
    listed: int | None = None


UNAVAILABLE = Shown(STATE_UNAVAILABLE)
RESTORED = Shown(STATE_UNAVAILABLE, restored=True)
UNKNOWN = Shown(STATE_UNKNOWN)
# As SUPPORTED answers: an alarm at 1700000000 s, shown in the tests' time zone,
# no timer, which the timers sensor shows as unavailable while it's available,
# notifications not enabled, which is Do Not Disturb on, and alarm volume 0.7
ANSWERED = {
    "alarms": Shown("2023-11-14T14:13:20-08:00", listed=1),
    "timers": Shown(STATE_UNAVAILABLE, listed=0),
    "do_not_disturb": Shown(STATE_ON),
    "alarm_volume": Shown("70"),
}
# The entities that need the device's address, by the end of their entity ID, and
# those for alarms and timers
ADDRESSED = ["device", "wi_fi_network", "signal_strength", "update", "reboot"]
FEATURES = list(ANSWERED)
DOMAINS = {
    "update": "binary_sensor",
    "reboot": "button",
    "do_not_disturb": "switch",
    "alarm_volume": "number",
}


@dataclass(frozen=True)
class Speaker:
    """A speaker of the test, and the updates from which each thing happens to it.

    mDNS reports its address just before update found_at. From update reachable_from,
    its alarms or else its info answer 200, so its firmware is checked, which says
    that no update is waiting. From update alarms_from, its alarms answer 200, so it
    has alarms, timers and settings entities; None if they never do.
    """

    device_id: str
    name: str
    address: str
    found_at: int
    reachable_from: int
    alarms_from: int | None

    def listed(self, address: str | None) -> Device:
        """Return the speaker as Google lists it, with this address from mDNS."""
        return found(self.device_id, address, name=self.name)

    def entity_id(self, key: str) -> str:
        """Return the ID of its entity that ends with this key."""
        prefix = self.name.lower().replace(" ", "_")
        return f"{DOMAINS.get(key, 'sensor')}.{prefix}_{key}"

    def expected(self, update: int, *, registered: bool) -> dict[str, Shown | None]:
        """Return what each of its entities shows after this update.

        As it did before updates without an address counted: those that need the
        address are unavailable until mDNS reports it, and the others aren't there
        until its alarms answer 200, or show as restored if a start before added them.
        """
        addressed: dict[str, Shown | None]
        features: dict[str, Shown | None]
        if update < self.found_at:
            addressed = dict.fromkeys(ADDRESSED, UNAVAILABLE)
        else:
            addressed = {
                "device": Shown(self.address),
                "wi_fi_network": UNKNOWN,
                "signal_strength": UNKNOWN,
                "update": Shown(STATE_OFF)
                if update >= self.reachable_from
                else UNKNOWN,
                "reboot": UNKNOWN,
            }
        if self.alarms_from is not None and update >= self.alarms_from:
            features = dict(ANSWERED)
        else:
            features = dict.fromkeys(
                FEATURES,
                RESTORED if registered and self.alarms_from is not None else None,
            )
        return {
            self.entity_id(key): shown
            for key, shown in {**addressed, **features}.items()
        }


HALLWAY = "10.0.0.4"
SPEAKERS = [
    # Found before its 5th update, and answers at once
    Speaker(SPEAKER_ID, SPEAKER_NAME, SPEAKER, 2, 2, 2),
    # Found later, then answers "not found" to everything for 3 updates as it starts
    Speaker("bedroom", "Bedroom speaker", BEDROOM, 7, 10, 10),
    # Found much later, and has no alarms: "not found" for them, and info without
    # Google Assistant
    Speaker("hallway", "Hallway speaker", HALLWAY, 12, 12, None),
]
# The update after which the integration's clock is past the hallway speaker's
# support check, and the update after that, which asks it only for its info
SUPPORT_CHECK = 17
LAST = 18


def shown(hass: HomeAssistant) -> dict[str, Shown | None]:
    """Return what each entity of the speakers shows now, None for one that isn't there."""
    result: dict[str, Shown | None] = {}
    for speaker in SPEAKERS:
        for key in ADDRESSED + FEATURES:
            entity_id = speaker.entity_id(key)
            entity_state = hass.states.get(entity_id)
            if entity_state is None:
                result[entity_id] = None
                continue
            attributes = entity_state.attributes
            listed = attributes.get(key) if key in {"alarms", "timers"} else None
            result[entity_id] = Shown(
                entity_state.state,
                attributes.get("restored", False),
                None if listed is None else len(listed),
            )
    return result


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    "registered",
    [
        pytest.param(False, id="first-start"),
        # Home Assistant has the entities from an earlier start, as after a power
        # cut. The integration's new client doesn't know which devices have no alarms.
        pytest.param(True, id="registered"),
    ],
)
async def test_speakers_start_with_home_assistant(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    replies: Replies,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
    registered: bool,
) -> None:
    """Show each speaker's entities as before updates without an address counted, at every update.

    The speakers are found after different numbers of updates, fewer and more than 5,
    and answer as a speaker that has alarms, one that is starting, and a device without
    alarms do, also once the integration finds that it has none. No entity becomes
    available later than it did: the updates without an address make only alarms,
    timers and settings entities unavailable, which Home Assistant adds only once the
    speaker answers.
    """
    bedroom = SPEAKERS[1]
    replies.update(
        {SPEAKER: dict(SUPPORTED), BEDROOM: dict(SUPPORTED), HALLWAY: dict(NO_ALARMS)}
    )
    if registered:
        google.return_value = [speaker.listed(speaker.address) for speaker in SPEAKERS]
        await set_up(hass, config_entry)
    google.return_value = [speaker.listed(None) for speaker in SPEAKERS]
    replies[BEDROOM] = dict(STARTING)
    if registered:
        assert await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()
    else:
        await set_up(hass, config_entry)

    # By update and entity, so a failure lists each one that differs
    timeline = {
        (1, entity_id): entity_shown for entity_id, entity_shown in shown(hass).items()
    }
    for update in range(2, LAST + 1):
        for speaker in SPEAKERS:
            if update == speaker.found_at:
                runtime(config_entry).client.found_devices.async_device_found(
                    speaker.device_id, speaker.name, speaker.address
                )
        if update == bedroom.alarms_from:
            replies[BEDROOM] = dict(SUPPORTED)
        seconds = SUPPORT_CHECK_DELAY if update == SUPPORT_CHECK else 15
        if update >= SUPPORT_CHECK:
            clock.return_value += seconds
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
        timeline |= {
            (update, entity_id): entity_shown
            for entity_id, entity_shown in shown(hass).items()
        }

    assert timeline == {
        (update, entity_id): entity_shown
        for update in range(1, LAST + 1)
        for speaker in SPEAKERS
        for entity_id, entity_shown in speaker.expected(
            update, registered=registered
        ).items()
    }
