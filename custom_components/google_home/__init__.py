"""Custom integration to integrate Google Home with Home Assistant.

For more details about this integration, please refer to
https://github.com/leikoilja/ha-google-home
"""

import asyncio
from collections.abc import Coroutine
from datetime import timedelta
import logging
from typing import cast

from aiohttp import ClientSession
from glocaltokens.utils.token import is_aas_et

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import const
from .api import GlocaltokensApiClient
from .bluetooth import BluetoothScanner, TrackerUpdate, bluetooth_now
from .bluetooth_coordinator import BluetoothCoordinator
from .bluetooth_storage import async_history
from .const import (
    BROWSER_TITLE,
    CONF_ANDROID_ID,
    CONF_BLUETOOTH_EXCLUDED,
    CONF_BLUETOOTH_TRACKING,
    CONF_EXCLUDED_HOMES,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    INTEGRATION_PAGE_URL,
    ISSUE_INVALID_INTERVAL,
    ISSUE_NO_ADDED_HOME,
    ISSUE_POLLING_DISABLED,
    MASTER_TOKEN_TITLE,
    NO_DEVICES_DOCS_URL,
    PLATFORMS,
    SUBENTRY_BLUETOOTH_DEVICE,
)
from .coordinator import GoogleAccountCoordinator
from .mdns import async_browse_cast_devices
from .sensor import async_setup_actions
from .types import GoogleHomeConfigEntry, GoogleHomeData

_LOGGER: logging.Logger = logging.getLogger(__package__)

# The integration is set up from the UI only. Pylint takes the schema, a
# function, for a variable and wants snake_case, but Home Assistant looks for
# this name.
# pylint: disable-next=invalid-name
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Titles that setup used when Google didn't say which account signed in
GENERIC_TITLES = {MASTER_TOKEN_TITLE, BROWSER_TITLE}


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register the actions, which exist whether or not the entry is loaded."""
    async_setup_actions(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        async_history(hass, entry)
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> None:
    """Migrate a config entry saved by an older version.

    Home Assistant itself refuses an entry from a newer major version, before
    calling this.
    """
    if entry.minor_version < 2:
        data = dict(entry.data)
        # Setup has always saved a master token, and the integration signs in
        # with it from then on, so a saved app password is never used again.
        if data.get(CONF_PASSWORD) and is_aas_et(data.get(CONF_MASTER_TOKEN) or ""):
            data[CONF_PASSWORD] = ""
            _LOGGER.debug("Cleared the app password, which is no longer used")
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)


async def async_setup_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> None:
    """Set up this integration using UI."""
    history = async_history(hass, entry)
    await history.async_load(bluetooth_now)
    username = cast(str, entry.data.get(CONF_USERNAME))
    password = cast(str, entry.data.get(CONF_PASSWORD))
    android_id = cast(str, entry.data.get(CONF_ANDROID_ID))
    master_token = cast(str, entry.data.get(CONF_MASTER_TOKEN))
    update_interval = configured_interval(entry)

    _LOGGER.debug("Coordinator update interval is: %s", update_interval)

    session = async_get_clientsession(hass, verify_ssl=False)

    zeroconf_instance = await zeroconf.async_get_instance(hass)
    glocaltokens_client = GlocaltokensApiClient(
        hass=hass,
        session=session,
        username=username,
        password=password,
        master_token=master_token,
        android_id=android_id,
        known_hosts=entry.options.get(CONF_KNOWN_HOSTS, []),
        excluded_homes=entry.options.get(CONF_EXCLUDED_HOMES, []),
    )

    account = GoogleAccountCoordinator(
        hass, entry, glocaltokens_client, update_interval
    )
    # Before the first refresh, which adds the device coordinators
    entry.runtime_data = GoogleHomeData(glocaltokens_client, account, {})
    glocaltokens_client.can_refresh_devices = account.async_can_refresh_devices
    found_devices = glocaltokens_client.found_devices
    # Not async_request_refresh(), which drops the request when an update that
    # started too early to fetch for found devices runs longer than its cooldown
    found_devices.request_update = account.async_refresh
    entry.async_on_unload(found_devices.async_stop)
    # Before the first refresh, so they also show while setup is retried
    async_show_polling_disabled(hass, entry)
    async_show_invalid_interval(hass, entry)
    # Before the first refresh, whose home graph decides it, so that a failed setup
    # also removes it
    async_show_no_added_home(hass, entry, glocaltokens_client)
    glocaltokens_client.polling_off = entry.pref_disable_polling
    if entry.pref_disable_polling:
        # The fetches for devices that mDNS finds are scheduled too, so they stop
        found_devices.async_stop()
    # Before the first refresh, so the devices that mDNS already knows are found
    # before setup fetches Google's list, which then covers them
    async_browse_cast_devices(hass, entry, zeroconf_instance, found_devices)

    glocaltokens_client.setting_up = True
    try:
        await account.async_config_entry_first_refresh()
        # Each device is asked once before its entities are added. Not a first
        # refresh, so a device whose update fails unexpectedly doesn't fail setup: it
        # gets its entities at its first update that works.
        await asyncio.gather(
            *(
                coordinator.async_refresh()
                for coordinator in entry.runtime_data.devices.values()
            )
        )
    finally:
        glocaltokens_client.setting_up = False

    entry.runtime_data.bluetooth_config = bluetooth_config(entry)
    bluetooth = entry.runtime_data.bluetooth = async_create_bluetooth_coordinator(
        hass, entry, session
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if bluetooth is not None:
        # Not a first refresh: Bluetooth must never fail or delay setup
        entry.async_create_background_task(
            hass,
            bluetooth.async_refresh(),
            "Start Bluetooth scans",
        )

    if entry.title in GENERIC_TITLES:
        entry.async_create_background_task(
            hass,
            async_name_after_account(hass, entry, glocaltokens_client),
            "Look up the Google account of the master token",
        )

    entry.async_on_unload(entry.add_update_listener(async_update_entry))


def bluetooth_config(
    entry: GoogleHomeConfigEntry,
) -> tuple[bool, frozenset[str], frozenset[str]]:
    """Return the settings that Bluetooth tracking is set up with.

    Adding or removing a tracked device only calls the entry's update listener,
    so it compares these to reload when they change.
    """
    return (
        bool(entry.options.get(CONF_BLUETOOTH_TRACKING, False)),
        frozenset(entry.options.get(CONF_BLUETOOTH_EXCLUDED, [])),
        frozenset(
            subentry.subentry_id
            for subentry in entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE)
        ),
    )


def bluetooth_changes(entry: GoogleHomeConfigEntry) -> list[str]:
    """Return each change since Bluetooth tracking was set up, to log why it reloads."""
    assert entry.runtime_data.bluetooth_config is not None
    old_tracking, old_excluded, old_subentry_ids = entry.runtime_data.bluetooth_config
    tracking, excluded, subentry_ids = bluetooth_config(entry)
    changes = []
    if subentry_ids - old_subentry_ids:
        changes.append("Bluetooth device added to tracking")
    if old_subentry_ids - subentry_ids:
        changes.append("Bluetooth device removed from tracking")
    if (tracking, excluded) != (old_tracking, old_excluded):
        changes.append("Bluetooth options changed")
    return changes


def async_create_bluetooth_coordinator(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry, session: ClientSession
) -> DataUpdateCoordinator[dict[str, TrackerUpdate]] | None:
    """Create the Bluetooth coordinator, if tracking is on and has devices to track."""
    tracking, excluded, subentry_ids = bluetooth_config(entry)
    entry.runtime_data.bluetooth_scanner = None
    if not tracking or not subentry_ids:
        return None
    scanner = BluetoothScanner(
        session,
        entry.runtime_data.account,
        entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE),
        excluded,
        async_history(hass, entry),
    )
    entry.runtime_data.bluetooth_scanner = scanner
    return BluetoothCoordinator(hass, entry, scanner, async_history(hass, entry))


@callback
def async_show_polling_disabled(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> None:
    """Show a repair while polling is turned off, which can turn it back on.

    Home Assistant reloads the entry when the setting changes, so setup shows or
    removes it. Removing it also forgets that the user hid it. It isn't kept over a
    restart, except whether it's hidden, and goes with the entry.
    """
    if not entry.pref_disable_polling:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_POLLING_DISABLED)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_POLLING_DISABLED,
        config_entry_id=entry.entry_id,
        data={"entry_id": entry.entry_id},
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_POLLING_DISABLED,
    )


@callback
def async_show_invalid_interval(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> None:
    """Show a repair while the saved update interval is below 1 second and polling is on.

    While polling is off, nothing uses the interval. Turning polling back on reloads
    the entry, whose setup then shows the repair. Setup shows or removes it, and so do
    changed options, which apply without a reload. Unloading keeps it, so it stays
    hidden over reloads and setup retries if the user hid it. Removing it, as setup
    does once polling is off, forgets that the user hid it. Home Assistant hides it
    while the entry is disabled and deletes it with the entry.
    """
    if saved_interval(entry) >= const.MIN_UPDATE_INTERVAL or entry.pref_disable_polling:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_INVALID_INTERVAL)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_INVALID_INTERVAL,
        config_entry_id=entry.entry_id,
        data={"entry_id": entry.entry_id},
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_INVALID_INTERVAL,
        translation_placeholders={"min_interval": str(const.MIN_UPDATE_INTERVAL)},
    )


@callback
def async_show_no_added_home(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry, client: GlocaltokensApiClient
) -> None:
    """Show a repair while Google's last home graph has no home whose devices are added.

    Each home graph that Google answers with decides, whichever update, device or
    action fetched it. Until the first one, and after a fetch that fails, the repair
    stays as it was. The account's homes are then all deselected, or Google reports
    none: one repair covers both, so it stays hidden when one becomes the other. It
    isn't kept over a restart, except whether it's hidden, and goes when the entry
    unloads, also if setup fails.
    """

    @callback
    def homes_answered(home_added: bool) -> None:
        if home_added:
            ir.async_delete_issue(hass, DOMAIN, ISSUE_NO_ADDED_HOME)
            return
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_NO_ADDED_HOME,
            config_entry_id=entry.entry_id,
            is_fixable=False,
            # Without an added home, every home in the graph has an ID
            learn_more_url=None if client.homes else NO_DEVICES_DOCS_URL,
            severity=ir.IssueSeverity.WARNING,
            translation_key="homes_deselected" if client.homes else "no_home",
            translation_placeholders={"integration_url": INTEGRATION_PAGE_URL},
        )

    @callback
    def stop_repair() -> None:
        # Detached, so that a fetch that Google answers later, such as an action's,
        # can't change the repair of the entry loaded again, or of a deleted one
        client.homes_answered = None
        ir.async_delete_issue(hass, DOMAIN, ISSUE_NO_ADDED_HOME)

    client.homes_answered = homes_answered
    entry.async_on_unload(stop_repair)


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


async def async_unload_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> None:
    """Handle removal of an entry."""
    _LOGGER.debug("Unloading entry...")
    # Manual update_entity callers are not entry-owned background tasks. Retire
    # their scanner before the first unload await can let an old reply land.
    if isinstance(bluetooth := entry.runtime_data.bluetooth, BluetoothCoordinator):
        bluetooth.stop()
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    await async_history(hass, entry).async_flush()


async def async_remove_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> None:
    """Remove only this entry's continuity after older writes finish."""
    await async_history(hass, entry).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting a device only when Google no longer returns it.

    Devices that are offline or not on the network stay in the account's data, so
    they come back on the next reload and can't be deleted. Nothing can be
    deleted while Google's device list is unknown: the entry isn't loaded, no
    fetch has succeeded yet, or a device rejected its token, got no new token
    that it accepts, and the list hasn't been fetched again.

    A deleted device stops updating, as one that the integration removes does, so if
    Google lists it again, it gets its entities back.

    Deleting a tracked Bluetooth device stops tracking it, as deleting it from the
    integration's page does: its subentry goes, with the device and its tracker.
    """
    if (subentry_id := device_entry.config_subentry_id) is not None:
        hass.config_entries.async_remove_subentry(entry, subentry_id)
        return True
    if (
        entry.state is not ConfigEntryState.LOADED
        or not entry.runtime_data.client.google_devices_fetched
    ):
        return False
    account = entry.runtime_data.account
    device_ids = {
        device_id for domain, device_id in device_entry.identifiers if domain == DOMAIN
    }
    if device_ids & account.data.keys():
        return False
    for device_id in device_ids:
        await account.async_forget_device(device_id)
    return True


def saved_interval(entry: GoogleHomeConfigEntry) -> int:
    """Return the update interval in the options, in seconds."""
    return cast(int, entry.options.get(CONF_UPDATE_INTERVAL, const.UPDATE_INTERVAL))


def configured_interval(entry: GoogleHomeConfigEntry) -> timedelta:
    """Return the update interval in the options, or the default for one below the minimum.

    The options form refuses such an interval, but earlier versions saved it: zero
    stopped scheduled updates and a negative one ran them without a pause. A repair
    says so and offers to fix it.
    """
    seconds = saved_interval(entry)
    return timedelta(
        seconds=seconds
        if seconds >= const.MIN_UPDATE_INTERVAL
        else const.UPDATE_INTERVAL
    )


@callback
def async_update_entry(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> Coroutine[object, object, None]:
    """Capture timing edits inline before HA schedules the options coroutine."""
    if isinstance(coordinator := entry.runtime_data.bluetooth, BluetoothCoordinator):
        coordinator.update_departure_delays()
    return _async_update_options(hass, entry)


async def _async_update_options(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> None:
    """Apply changed options."""
    client = entry.runtime_data.client
    # Known hosts are looked up when Google's device list is fetched, at setup. The
    # devices of excluded homes are removed when it's fetched after the reload.
    if (
        entry.options.get(CONF_KNOWN_HOSTS, []) != client.known_hosts
        or set(entry.options.get(CONF_EXCLUDED_HOMES, [])) != client.excluded_homes
    ):
        _LOGGER.debug("Known hosts or homes changed, reloading...")
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    if changes := bluetooth_changes(entry):
        _LOGGER.debug("%s, reloading...", " and ".join(changes))
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    _LOGGER.debug("Options updated, updating coordinator interval...")
    async_show_invalid_interval(hass, entry)
    data = entry.runtime_data
    update_interval = configured_interval(entry)
    data.account.update_interval = update_interval
    for coordinator in data.devices.values():
        coordinator.update_interval = update_interval
    _LOGGER.debug("Coordinator update interval is: %s", update_interval)
