"""Tests for how Google Home entities are named and when they are available."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
import logging
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from custom_components.google_home.button import RebootButton
from custom_components.google_home.const import DOMAIN
from custom_components.google_home.entity import GoogleHomeBaseEntity
from custom_components.google_home.models import GoogleHomeDevice
from custom_components.google_home.number import AlarmVolumeNumber
from custom_components.google_home.sensor import (
    GoogleHomeAlarmsSensor,
    GoogleHomeDeviceSensor,
    GoogleHomeTimersSensor,
)
from custom_components.google_home.switch import DoNotDisturbSwitch
from custom_components.google_home.types import GoogleHomeConfigEntry

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant import loader
from homeassistant.config_entries import SOURCE_USER, ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import EntityPlatform

# pylint: enable=wrong-import-order

DEVICE_ID = "device-id"

# Each entity's ID ending and name, as Home Assistant in English shows them after
# the device name
ENTITIES = [
    (GoogleHomeAlarmsSensor, "sensor", "alarms", "Alarms"),
    (GoogleHomeTimersSensor, "sensor", "timers", "Timers"),
    (GoogleHomeDeviceSensor, "sensor", "device", "Device"),
    (DoNotDisturbSwitch, "switch", "do_not_disturb", "Do Not Disturb"),
    (AlarmVolumeNumber, "number", "alarm_volume", "Alarm volume"),
    (RebootButton, "button", "reboot", "Reboot"),
]
ENTITY_SUFFIXES = [suffix for _, _, suffix, _ in ENTITIES]
# The same in German, whose entity IDs use the German names
GERMAN_ENTITIES = [
    (GoogleHomeAlarmsSensor, "sensor", "wecker", "Wecker"),
    (GoogleHomeTimersSensor, "sensor", "timer", "Timer"),
    (GoogleHomeDeviceSensor, "sensor", "gerat", "Gerät"),  # codespell:ignore
    (DoNotDisturbSwitch, "switch", "bitte_nicht_storen", "Bitte nicht stören"),
    (AlarmVolumeNumber, "number", "weckerlautstarke", "Weckerlautstärke"),
    (RebootButton, "button", "neu_starten", "Neu starten"),
]
# Earlier versions named entities "<Google name> <label>", with unique IDs
# "<device ID>/<label>"
OLD_LABELS: dict[type[GoogleHomeBaseEntity], str] = {
    GoogleHomeAlarmsSensor: "alarms",
    GoogleHomeTimersSensor: "timers",
    GoogleHomeDeviceSensor: "device",
    DoNotDisturbSwitch: "Do Not Disturb",
    AlarmVolumeNumber: "alarm volume",
    RebootButton: "reboot",
}


@asynccontextmanager
async def home_assistant(
    config_dir: Path, language: str = "en"
) -> AsyncIterator[tuple[HomeAssistant, GoogleHomeConfigEntry]]:
    """Start Home Assistant in this language with a config entry of this integration.

    It starts the registries, and the loader that finds this integration's translations.
    """
    hass = HomeAssistant(str(config_dir))
    hass.config.language = language
    try:
        loader.async_setup(hass)
        dr.async_setup(hass)
        hass.config_entries = ConfigEntries(hass, {})
        await hass.config_entries.async_initialize()
        for registry in (ar, dr, er):
            await registry.async_load(hass, load_empty=True)
        entry: GoogleHomeConfigEntry = ConfigEntry(
            data={},
            discovery_keys=MappingProxyType({}),
            domain=DOMAIN,
            minor_version=1,
            options={},
            source=SOURCE_USER,
            subentries_data=None,
            title="Google Home",
            unique_id=None,
            version=1,
        )
        # Register the entry without setting it up, as Home Assistant's own
        # MockConfigEntry does
        hass.config_entries._entries[entry.entry_id] = entry  # noqa: SLF001  # pylint: disable=protected-access
        yield hass, entry
    finally:
        await hass.async_stop(force=True)


def add_device(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    google_name: str,
    area: str | None,
) -> str:
    """Add the device as the integration describes it, put it in an area, return its ID."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, DEVICE_ID)},
        name=google_name,
    )
    if area is not None:
        area_id = ar.async_get(hass).async_create(area).id
        dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    return device.id


def make_entity(
    entity_class: type[GoogleHomeBaseEntity], google_name: str
) -> GoogleHomeBaseEntity:
    """Return an entity of a device that answers, named as in the Google Home app."""
    device = GoogleHomeDevice(DEVICE_ID, google_name, "token", "10.0.0.2")
    coordinator = Mock(data=device, last_update_success=True)
    return entity_class(coordinator, Mock(), DEVICE_ID, google_name, None)


async def add_entity(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    domain: str,
    new: GoogleHomeBaseEntity,
) -> str:
    """Add the entity as its platform does and return its entity ID."""
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain=domain,
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    # Setting up a platform loads the entity names in Home Assistant's language
    await platform.platform_data.async_load_translations()
    await platform.async_add_entities([new])
    assert new.entity_id in platform.entities
    return new.entity_id


def friendly_name(hass: HomeAssistant, entity_id: str) -> object:
    """Return the name Home Assistant shows for the entity."""
    state = hass.states.get(entity_id)
    assert state is not None
    return state.attributes["friendly_name"]


@pytest.mark.parametrize(
    ("entity_class", "domain", "suffix", "name"), ENTITIES, ids=ENTITY_SUFFIXES
)
def test_new_entity_follows_device_renamed_in_home_assistant(
    tmp_path: Path,
    entity_class: type[GoogleHomeBaseEntity],
    domain: str,
    suffix: str,
    name: str,
) -> None:
    """Use the device's Home Assistant name, not its Google Home name, for new entities.

    Renaming "Bathroom speaker" to "Speaker" leaves the room to the area, as Home
    Assistant suggests. New entities repeated the Google name in their entity IDs and
    names, such as button.bathroom_speaker_bathroom_speaker_reboot.
    """

    async def run() -> None:
        async with home_assistant(tmp_path) as (hass, entry):
            device_id = add_device(hass, entry, "Bathroom speaker", "Bathroom")
            dr.async_get(hass).async_update_device(device_id, name_by_user="Speaker")

            entity_id = await add_entity(
                hass, entry, domain, make_entity(entity_class, "Bathroom speaker")
            )

            assert entity_id == f"{domain}.bathroom_speaker_{suffix}"
            assert friendly_name(hass, entity_id) == f"Speaker {name}"

    asyncio.run(run())


def test_new_entity_keeps_room_in_device_name(tmp_path: Path) -> None:
    """Leave the entity ID to Home Assistant's format, which starts with the area.

    The room in the Google name then appears twice, as the docs explain.
    """

    async def run() -> None:
        async with home_assistant(tmp_path) as (hass, entry):
            add_device(hass, entry, "Bathroom speaker", "Bathroom")

            entity_id = await add_entity(
                hass, entry, "button", make_entity(RebootButton, "Bathroom speaker")
            )

            assert entity_id == "button.bathroom_bathroom_speaker_reboot"
            assert friendly_name(hass, entity_id) == "Bathroom speaker Reboot"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("entity_class", "domain", "suffix", "name"), ENTITIES, ids=ENTITY_SUFFIXES
)
def test_new_entity_of_device_without_area(
    tmp_path: Path,
    entity_class: type[GoogleHomeBaseEntity],
    domain: str,
    suffix: str,
    name: str,
) -> None:
    """Give a device without an area the entity IDs that the docs show."""

    async def run() -> None:
        async with home_assistant(tmp_path) as (hass, entry):
            add_device(hass, entry, "Living Room", None)

            entity_id = await add_entity(
                hass, entry, domain, make_entity(entity_class, "Living Room")
            )

            assert entity_id == f"{domain}.living_room_{suffix}"
            assert friendly_name(hass, entity_id) == f"Living Room {name}"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("entity_class", "domain", "suffix", "name"), ENTITIES, ids=ENTITY_SUFFIXES
)
def test_upgrade_keeps_entity_id_and_name(
    tmp_path: Path,
    entity_class: type[GoogleHomeBaseEntity],
    domain: str,
    suffix: str,
    name: str,
) -> None:
    """Keep the entity ID and shown name of an entity that an earlier version added."""
    label = OLD_LABELS[entity_class]

    async def run() -> None:
        async with home_assistant(tmp_path) as (hass, entry):
            device_id = add_device(hass, entry, "Bathroom speaker", "Bathroom")
            registry = er.async_get(hass)
            old = registry.async_get_or_create(
                domain,
                DOMAIN,
                f"{DEVICE_ID}/{label}",
                config_entry=entry,
                device_id=device_id,
                has_entity_name=False,
                object_id_base=f"Bathroom speaker {label}",
                original_name=f"Bathroom speaker {label}",
            )
            # Home Assistant's default entity ID format puts the area first
            assert old.entity_id == f"{domain}.bathroom_bathroom_speaker_{suffix}"
            assert (
                er.async_get_legacy_friendly_name(hass, old)
                == f"Bathroom speaker {name}"
            )

            entity_id = await add_entity(
                hass, entry, domain, make_entity(entity_class, "Bathroom speaker")
            )

            assert entity_id == old.entity_id
            entry_after = registry.async_get(entity_id)
            assert entry_after is not None
            # The registry entry now uses the new naming
            assert entry_after.has_entity_name
            assert friendly_name(hass, entity_id) == f"Bathroom speaker {name}"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("entity_class", "domain", "suffix", "name"), GERMAN_ENTITIES, ids=ENTITY_SUFFIXES
)
def test_new_entity_named_in_german(
    tmp_path: Path,
    entity_class: type[GoogleHomeBaseEntity],
    domain: str,
    suffix: str,
    name: str,
) -> None:
    """Name new entities in German, and build their IDs from the German names.

    The IDs start with the area and the device name, as in English.
    """

    async def run() -> None:
        async with home_assistant(tmp_path, "de") as (hass, entry):
            add_device(hass, entry, "Lautsprecher", "Küche")

            entity_id = await add_entity(
                hass, entry, domain, make_entity(entity_class, "Lautsprecher")
            )

            assert entity_id == f"{domain}.kuche_lautsprecher_{suffix}"
            assert friendly_name(hass, entity_id) == f"Lautsprecher {name}"

    asyncio.run(run())


def test_new_entity_named_in_russian_keeps_english_id(tmp_path: Path) -> None:
    """Name new entities in Russian, with entity IDs from the English names."""

    async def run() -> None:
        async with home_assistant(tmp_path, "ru") as (hass, entry):
            add_device(hass, entry, "Lautsprecher", "Küche")

            entity_id = await add_entity(
                hass,
                entry,
                "sensor",
                make_entity(GoogleHomeAlarmsSensor, "Lautsprecher"),
            )

            assert entity_id == "sensor.kuche_lautsprecher_alarms"
            assert friendly_name(hass, entity_id) == "Lautsprecher Будильники"

    asyncio.run(run())


def test_language_keeps_entity_id_until_recreated(tmp_path: Path) -> None:
    """Keep an English entity ID in German; recreating entity IDs suggests the German one.

    In German, Home Assistant builds entity IDs from the German names. It doesn't
    change an existing entity ID, but Recreate entity IDs uses the new name.
    """

    async def run() -> None:
        async with home_assistant(tmp_path, "de") as (hass, entry):
            device_id = add_device(hass, entry, "Kitchen speaker", None)
            registry = er.async_get(hass)
            # As the previous version, with English names, added it
            old = registry.async_get_or_create(
                "sensor",
                DOMAIN,
                f"{DEVICE_ID}/alarms",
                config_entry=entry,
                device_id=device_id,
                has_entity_name=True,
                object_id_base="Alarms",
                original_name="Alarms",
            )
            assert old.entity_id == "sensor.kitchen_speaker_alarms"

            entity_id = await add_entity(
                hass,
                entry,
                "sensor",
                make_entity(GoogleHomeAlarmsSensor, "Kitchen speaker"),
            )

            assert entity_id == old.entity_id
            assert friendly_name(hass, entity_id) == "Kitchen speaker Wecker"
            entry_after = registry.async_get(entity_id)
            assert entry_after is not None
            # What Recreate entity IDs offers
            assert (
                registry.async_regenerate_entity_id(entry_after)
                == "sensor.kitchen_speaker_wecker"
            )

    asyncio.run(run())


def test_upgrade_keeps_entity_id_and_name_set_by_user(tmp_path: Path) -> None:
    """Keep an entity ID and name that the user changed."""

    async def run() -> None:
        async with home_assistant(tmp_path) as (hass, entry):
            device_id = add_device(hass, entry, "Bathroom speaker", "Bathroom")
            registry = er.async_get(hass)
            old = registry.async_get_or_create(
                "button",
                DOMAIN,
                f"{DEVICE_ID}/reboot",
                config_entry=entry,
                device_id=device_id,
                has_entity_name=False,
                object_id_base="Bathroom speaker reboot",
                original_name="Bathroom speaker reboot",
            )
            registry.async_update_entity(
                old.entity_id, new_entity_id="button.my_reboot", name="My reboot"
            )

            entity_id = await add_entity(
                hass, entry, "button", make_entity(RebootButton, "Bathroom speaker")
            )

            assert entity_id == "button.my_reboot"
            entry_after = registry.async_get(entity_id)
            assert entry_after is not None
            assert entry_after.name == "My reboot"
            # Home Assistant puts the device name before a name the user set
            assert friendly_name(hass, entity_id) == "Bathroom speaker My reboot"

    asyncio.run(run())


@pytest.mark.parametrize(
    "entity_class", [row[0] for row in ENTITIES], ids=ENTITY_SUFFIXES
)
def test_entity_unavailable_when_google_no_longer_lists_device(
    entity_class: type,
) -> None:
    """Show every entity of a device removed in the Google Home app as unavailable.

    Otherwise the switch would show off and the alarm volume 0.
    """
    device = GoogleHomeDevice("device-id", "Kitchen", "token", "10.0.0.2")
    coordinator = Mock(data=device, last_update_success=True)
    entity = entity_class(coordinator, Mock(), "device-id", "Kitchen", None)
    assert entity.available

    # As the account's update leaves the device's coordinator
    coordinator.data = None

    assert not entity.available


def test_unique_id_ignores_device_name() -> None:
    """Keep entity IDs when a device's name changes, as they follow the unique ID."""
    before = GoogleHomeAlarmsSensor(Mock(), Mock(), "pair", "Den speaker left", None)
    after = GoogleHomeAlarmsSensor(Mock(), Mock(), "pair", "Den speakers", None)

    assert before.unique_id == after.unique_id == "pair/alarms"
