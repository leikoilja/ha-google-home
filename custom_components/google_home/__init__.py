"""Custom integration to integrate Google Home with Home Assistant.

For more details about this integration, please refer to
https://github.com/leikoilja/ha-google-home
"""

from datetime import timedelta
import logging
from typing import cast

from glocaltokens.utils.token import is_aas_et

from homeassistant.components import zeroconf
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import (
    BROWSER_TITLE,
    CONF_ANDROID_ID,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_UPDATE_INTERVAL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    MASTER_TOKEN_TITLE,
    PLATFORMS,
    SENSOR,
    STARTUP_MESSAGE,
    UPDATE_INTERVAL,
)
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Titles that setup used when Google didn't say which account signed in
GENERIC_TITLES = {MASTER_TOKEN_TITLE, BROWSER_TITLE}


async def async_migrate_entry(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> bool:
    """Migrate a config entry saved by an older version."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        data = dict(entry.data)
        # Setup has always saved a master token, and the integration signs in
        # with it from then on, so a saved app password is never used again.
        if data.get(CONF_PASSWORD) and is_aas_et(data.get(CONF_MASTER_TOKEN) or ""):
            data[CONF_PASSWORD] = ""
            _LOGGER.debug("Cleared the app password, which is no longer used")
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> bool:
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    username = cast(str, entry.data.get(CONF_USERNAME))
    password = cast(str, entry.data.get(CONF_PASSWORD))
    android_id = cast(str, entry.data.get(CONF_ANDROID_ID))
    master_token = cast(str, entry.data.get(CONF_MASTER_TOKEN))
    update_interval = cast(
        int, entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
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
        known_hosts=entry.options.get(CONF_KNOWN_HOSTS, []),
    )

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=SENSOR,
        update_method=glocaltokens_client.update_google_devices_information,
        update_interval=timedelta(seconds=update_interval),
        config_entry=entry,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: glocaltokens_client,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if entry.title in GENERIC_TITLES:
        entry.async_create_background_task(
            hass,
            async_name_after_account(hass, entry, glocaltokens_client),
            "Look up the Google account of the master token",
        )

    entry.async_on_unload(entry.add_update_listener(async_update_entry))
    return True


async def async_name_after_account(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry, client: GlocaltokensApiClient
) -> None:
    """Name an entry with a generic title after its Google account.

    Setup gives an entry a generic title when it doesn't know the account: older
    versions always did for a master token, and browser sign-in does when Google
    doesn't give the email address. Only the title changes: the saved username
    stays empty, so the integration keeps signing in exactly as before.
    """
    email = await client.async_get_email()
    # The user may have renamed the entry while Google was answering
    if email and entry.title in GENERIC_TITLES:
        hass.config_entries.async_update_entry(entry, title=email)


async def async_unload_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> bool:
    """Handle removal of an entry."""
    _LOGGER.debug("Unloading entry...")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting a device only when Google no longer returns it.

    Devices that are offline or not on the network stay in the coordinator data,
    so they come back on the next reload and can't be deleted. Nothing can be
    deleted while Google's device list is unknown: the entry isn't loaded, no
    fetch has succeeded yet, or a device rejected its token and the list hasn't
    been fetched again.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None or not entry_data[DATA_CLIENT].google_devices_fetched:
        return False
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]] = entry_data[
        DATA_COORDINATOR
    ]
    google_ids = {(DOMAIN, device.device_id) for device in coordinator.data}
    return not device_entry.identifiers & google_ids


async def async_update_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> None:
    """Apply changed options."""
    client: GlocaltokensApiClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    # Known hosts are looked up when Google's device list is fetched, at setup
    if entry.options.get(CONF_KNOWN_HOSTS, []) != client.known_hosts:
        _LOGGER.debug("Known hosts changed, reloading...")
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    _LOGGER.debug("Options updated, updating coordinator interval...")
    update_interval: int = entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    coordinator.update_interval = timedelta(seconds=update_interval)
    _LOGGER.debug(
        "Coordinator update interval is: %s", timedelta(seconds=update_interval)
    )
