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
from .bluetooth import async_connect_scanner
from .const import (
    BT_COORDINATOR,
    BT_UPDATE_INTERVAL,
    CONF_ANDROID_ID,
    CONF_BT_UPDATE_INTERVAL,
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


async def async_setup_entry(  # type: ignore
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    username: str | None = entry.data.get(CONF_USERNAME)
    password: str | None = entry.data.get(CONF_PASSWORD)
    android_id: str | None = entry.data.get(CONF_ANDROID_ID)
    master_token: str | None = entry.data.get(CONF_MASTER_TOKEN)
    update_interval: int = entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
    bt_update_interval: int = entry.options.get(
        CONF_BT_UPDATE_INTERVAL, BT_UPDATE_INTERVAL
    )

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
        bt_update_interval=bt_update_interval,
    )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=SENSOR,
        update_method=glocaltokens_client.update_google_devices_information,
        update_interval=timedelta(seconds=update_interval),
    )
    bt_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_bt",
        update_method=glocaltokens_client.update_google_devices_bt_information,
        update_interval=timedelta(seconds=bt_update_interval),
    )

    await coordinator.async_config_entry_first_refresh()
    await bt_coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: glocaltokens_client,
        DATA_COORDINATOR: coordinator,
        BT_COORDINATOR: bt_coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _scanners, unload_scanner = async_connect_scanner(hass, bt_coordinator)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry.async_on_unload(unload_scanner)
    return True


async def update_listener(  # type: ignore
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update."""
    # Reload entry to update data
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(  # type: ignore
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Handle removal of an entry."""
    _LOGGER.debug("Unloading entry...")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
