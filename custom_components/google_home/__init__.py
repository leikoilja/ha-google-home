"""
Custom integration to integrate Google Home with Home Assistant.

For more details about this integration, please refer to
https://github.com/leikoilja/ha-google-home
"""
import asyncio
from datetime import timedelta
import logging

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    PLATFORMS,
    SENSOR,
    STARTUP_MESSAGE,
    UPDATE_INTERVAL,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


# Remove after updating to 2021.4.0
async def async_setup(
    _hass: HomeAssistant,
    _config: dict,  # type: ignore[type-arg]
) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    android_id = entry.data.get(CONF_ANDROID_ID)
    master_token = entry.data.get(CONF_MASTER_TOKEN)

    session = async_get_clientsession(hass, verify_ssl=False)

    zeroconf_instance = await zeroconf.async_get_instance(hass)
    glocaltokens_client = GlocaltokensApiClient(
        hass=hass,
        session=session,
        username=username,
        password=password,
        master_token=master_token,
        android_id=android_id,
        zeroconf_instance=zeroconf_instance,
    )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=SENSOR,
        update_method=glocaltokens_client.update_google_devices_information,
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
    )

    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: glocaltokens_client,
        DATA_COORDINATOR: coordinator,
    }

    # Offload the loading of entities to the platform
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    entry.add_update_listener(async_reload_entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
