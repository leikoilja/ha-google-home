"""
Custom integration to integrate Google Home with Home Assistant.

For more details about this integration, please refer to
https://github.com/leikoilja/ha-google-home
"""
from datetime import timedelta
import logging

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    CONF_UPDATE_INTERVAL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    PLATFORMS,
    SENSOR,
    STARTUP_MESSAGE,
    UPDATE_INTERVAL,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    username: str = entry.data.get(CONF_USERNAME)
    password: str = entry.data.get(CONF_PASSWORD)
    android_id: str = entry.data.get(CONF_ANDROID_ID)
    master_token: str = entry.data.get(CONF_MASTER_TOKEN)
    update_interval: int = entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)

    _LOGGER.debug(
        "Coordinator update interval is: %s", timedelta(seconds=update_interval)
    )

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
        update_interval=timedelta(seconds=update_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: glocaltokens_client,
        DATA_COORDINATOR: coordinator,
    }

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    entry.add_update_listener(async_update_entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    _LOGGER.debug("Unloading entry...")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update config entry."""
    _LOGGER.debug("Updating entry...")
    update_interval: int = entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    coordinator.update_interval = timedelta(seconds=update_interval)
    _LOGGER.debug(
        "Coordinator update interval is: %s", timedelta(seconds=update_interval)
    )
