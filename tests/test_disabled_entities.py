"""Retry guidance when polling is off and entities are individually disabled."""

import asyncio
from unittest.mock import Mock, patch

from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.google_home.const import DOMAIN

# ruff sorts homeassistant as first-party, pylint as third-party
# pylint: disable=wrong-import-order
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import BEDROOM_ID, Replies, kitchen_speaker
from .test_coordinators import BEDROOM_ALARMS
from .test_disabled_devices import kitchen_device, run_updates, set_disabled
from .test_missing_devices import failure_logged, logged
from .test_offline_devices import SILENT
from .test_polling_off import set_up_without_polling
from .test_removed_devices import fetch_list
from .test_setup import DEVICE_SENSOR
from .test_unsupported_devices import SPEAKER

# pylint: enable=wrong-import-order


@pytest.mark.usefixtures("two_speakers")
@pytest.mark.parametrize("unlisted", [False, True], ids=["listed", "unlisted"])
@pytest.mark.parametrize(
    "remaining",
    [
        None,
        Platform.SENSOR,
        Platform.BUTTON,
        Platform.BINARY_SENSOR,
        Platform.NUMBER,
        Platform.SWITCH,
    ],
    ids=["none", "sensor", "button", "binary sensor", "number", "switch"],
)
async def test_fetch_failure_with_individually_disabled_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
    remaining: Platform | None,
    unlisted: bool,
) -> None:
    """Say to reload only when no entity can request another account fetch.

    Individually disabling every sensor prevents Refresh devices from working,
    but any added non-sensor entity still supports Home Assistant's update_entity,
    even when unavailable after Google stops listing the device. Another device
    stays disabled throughout, so its entities cannot supply a refresh path.
    """
    await set_up_without_polling(hass, config_entry)
    await set_disabled(
        hass,
        device_registry,
        kitchen_device(device_registry, config_entry).id,
        disabled=True,
    )
    if unlisted:
        google.return_value = [kitchen_speaker()]
        await fetch_list(hass, config_entry, clock, 1)
        assert config_entry.runtime_data.devices[BEDROOM_ID].data is None

    started, release = asyncio.Event(), asyncio.Event()
    error = ClientConnectionError("Google is unreachable")

    async def fail_fetch(**_options: object) -> None:
        started.set()
        await release.wait()
        raise error

    clock.return_value = config_entry.runtime_data.client.next_scheduled_fetch
    kept: str | None = None
    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.async_get_google_devices_and_home_graph",
        side_effect=fail_fetch,
    ):
        refresh = asyncio.create_task(
            hass.services.async_call(
                DOMAIN,
                "refresh_devices",
                {ATTR_ENTITY_ID: BEDROOM_ALARMS},
                blocking=True,
            )
        )
        await started.wait()
        entities = er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
        for entity in entities:
            if (
                kept is None
                and entity.domain == remaining
                and entity.unique_id.startswith(f"{BEDROOM_ID}/")
                and not entity.disabled
            ):
                kept = entity.entity_id
            elif not entity.disabled:
                entity_registry.async_update_entity(
                    entity.entity_id, disabled_by=er.RegistryEntryDisabler.USER
                )
        release.set()
        await refresh
        await hass.async_block_till_done(wait_background_tasks=True)

    assert (kept is None) == (remaining is None)
    enabled = {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
        if not entity.disabled
    }
    assert enabled == ({kept} if kept else set())
    if kept:
        assert hass.states.get(kept) is not None
        expected = failure_logged(error, 20)
    else:
        expected = (
            "ERROR",
            "Failed to fetch Google's device list "
            f"(polling is off, so reload the integration to fetch it): {error}",
        )
    assert [line for level, line in logged(caplog) if level == "ERROR"] == [expected[1]]

    fetched = google.call_count
    # Flush pending debounced work before advancing beyond the next fetch time.
    for _ in range(20 * 60 // 15):
        clock.return_value += 15
        await run_updates(hass, freezer, 15)
    assert google.call_count == fetched
    await hass.services.async_call(
        DOMAIN, "refresh_devices", {ATTR_ENTITY_ID: ENTITY_MATCH_ALL}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert google.call_count == fetched + (remaining == Platform.SENSOR)

    if remaining != Platform.SENSOR:
        assert await async_setup_component(hass, "homeassistant", {})
        await hass.services.async_call(
            "homeassistant",
            "update_entity",
            {ATTR_ENTITY_ID: kept or [entity.entity_id for entity in entities]},
            blocking=True,
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert google.call_count == fetched + bool(kept)

    if kept is None:
        # The advertised recovery action fetches even with every entity disabled.
        assert await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert google.call_count == fetched + 1


@pytest.mark.parametrize("remaining", [Platform.NUMBER, Platform.SWITCH])
async def test_registered_but_unadded_entity_cannot_refresh(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    google: Mock,
    clock: Mock,
    entity_registry: er.EntityRegistry,
    replies: Replies,
    caplog: pytest.LogCaptureFixture,
    remaining: Platform,
) -> None:
    """A registered feature entity supplies no update_entity path until it is added.

    After a restart while the speaker is offline, its number and switch stay
    registered but aren't added until it answers. The device sensor still lets
    Refresh devices start a fetch; disabling it during that fetch leaves no path.
    """
    await set_up_without_polling(hass, config_entry)
    replies[SPEAKER] = dict(SILENT)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    started, release = asyncio.Event(), asyncio.Event()
    error = ClientConnectionError("Google is unreachable")

    async def fail_fetch(**_options: object) -> None:
        started.set()
        await release.wait()
        raise error

    clock.return_value = config_entry.runtime_data.client.next_scheduled_fetch
    with patch(
        "glocaltokens.client.GLocalAuthenticationTokens.async_get_google_devices_and_home_graph",
        side_effect=fail_fetch,
    ):
        refresh = asyncio.create_task(
            hass.services.async_call(
                DOMAIN,
                "refresh_devices",
                {ATTR_ENTITY_ID: DEVICE_SENSOR},
                blocking=True,
            )
        )
        await started.wait()
        kept = []
        for entity in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        ):
            if entity.domain == remaining:
                assert not entity.disabled
                kept.append(entity.entity_id)
            elif not entity.disabled:
                entity_registry.async_update_entity(
                    entity.entity_id, disabled_by=er.RegistryEntryDisabler.USER
                )
        release.set()
        await refresh
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(kept) == 1
    assert (
        "ERROR",
        "Failed to fetch Google's device list "
        f"(polling is off, so reload the integration to fetch it): {error}",
    ) in logged(caplog)
    fetched = google.call_count
    clock.return_value = config_entry.runtime_data.client.next_scheduled_fetch
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant", "update_entity", {ATTR_ENTITY_ID: kept}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert google.call_count == fetched
    assert f"Entity {kept[0]} not found" in caplog.text
