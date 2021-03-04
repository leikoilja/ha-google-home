"""
Custom integration to integrate Google Home with Home Assistant.

For more details about this integration, please refer to
https://github.com/leikoilja/ha-google-home
"""
import asyncio
import logging
from datetime import timedelta

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Config
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import CONF_ANDROID_ID
from .const import CONF_PASSWORD
from .const import CONF_USERNAME
from .const import DOMAIN
from .const import PLATFORMS
from .const import SENSOR
from .const import STARTUP_MESSAGE
from .const import UPDATE_INTERVAL


_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    android_id = entry.data.get(CONF_ANDROID_ID)

    session = async_get_clientsession(hass, verify_ssl=False)

    glocaltokens_client = GlocaltokensApiClient(
        hass, username, password, session, android_id
    )

    zeroconf_instance = await zeroconf.async_get_instance(hass)
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=SENSOR,
        update_method=lambda: glocaltokens_client.get_google_devices_information(
            zeroconf_instance
        ),
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
    )

    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Offload the loading of entities to the platform
    for platform in PLATFORMS:
        hass.async_add_job(
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
