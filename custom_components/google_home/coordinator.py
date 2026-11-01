"""The coordinators: one for the Google account's device list, and one for each device."""

from datetime import timedelta
import logging
from typing import override

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .const import DOMAIN, HOME_GRAPHS_BEFORE_REMOVAL
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleAccountCoordinator(DataUpdateCoordinator[dict[str, GoogleHomeDevice]]):
    """Google's list of the account's devices, by ID, and a coordinator for each device.

    Each update starts a round in which Google's list is fetched at most once, whether
    the update, a device or an action asks for it. Then the device coordinators follow
    the list: a device Google stops listing has no data, and a device that is new, listed
    again or just found at a known host is asked once straight away. Its coordinator
    stays, with its entities, until the entry unloads or the device is removed.
    """

    config_entry: GoogleHomeConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoogleHomeConfigEntry,
        client: GlocaltokensApiClient,
        update_interval: timedelta,
    ) -> None:
        """Create the coordinator of the account's device list."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Google Home account",
            update_interval=update_interval,
        )
        self.client = client
        # By ID, the device object that each device's coordinator was last asked
        # straight away to update
        self._asked: dict[str, GoogleHomeDevice] = {}

    @override
    async def _async_update_data(self) -> dict[str, GoogleHomeDevice]:
        """Fetch Google's list when due, and make the device coordinators follow it.

        Without devices, which is always the case at setup, the update fails while
        Google rejects the master token. Otherwise the devices keep updating, as those
        whose local tokens Google issued earlier may still answer, and Home Assistant
        asks to sign in again meanwhile.
        """
        known_hosts = await self.client.async_update_device_list()
        if (error := self.client.sign_in_error) is not None:
            if not self.client.google_devices:
                raise ConfigEntryAuthFailed(str(error)) from error
            self.async_ask_to_sign_in_if_rejected()
        listed = {device.device_id: device for device in self.client.google_devices}
        coordinators = self.config_entry.runtime_data.devices
        for device_id in coordinators.keys() - listed.keys():
            coordinators[device_id].async_unlisted()
        await self._async_remove_unlisted_devices(listed)
        # Setup asks the devices of its first update itself. A device found while
        # setup still runs, after that, is asked at the next update.
        loaded = self.config_entry.state is ConfigEntryState.LOADED
        for device_id, device in listed.items():
            coordinator = coordinators.get(device_id)
            if coordinator is None:
                coordinator = coordinators[device_id] = GoogleHomeDeviceCoordinator(
                    self.hass,
                    self.config_entry,
                    self.client,
                    device,
                    self.update_interval,
                )
            if host := known_hosts.get(device_id):
                coordinator.info_answered = (device, host)
            # A device that is new or listed again is asked once, also while that
            # update runs or after it fails, and one just found at a known host too
            new = (
                coordinator.data is not device
                and self._asked.get(device_id) is not device
            )
            if loaded and (host or new):
                self._asked[device_id] = device
                self.config_entry.async_create_background_task(
                    self.hass, coordinator.async_refresh(), f"Update {device.name}"
                )
        return listed

    async def _async_remove_unlisted_devices(
        self, listed: dict[str, GoogleHomeDevice]
    ) -> None:
        """Remove the entry's devices that enough home graphs in a row lack, with their entities.

        That includes a device that no home graph has had since the integration loaded,
        as Google may have dropped it before. A device that the last home graph has in
        an excluded home is removed at once. Nothing is removed while the list is
        unknown. A device that Google lists again later gets a new coordinator and
        entities.
        """
        if not self.client.google_devices_fetched:
            return
        registry = dr.async_get(self.hass)
        registered = {
            device_id: device
            for device in dr.async_entries_for_config_entry(
                registry, self.config_entry.entry_id
            )
            for domain, device_id in device.identifiers
            if domain == DOMAIN
        }
        coordinators = self.config_entry.runtime_data.devices
        for device_id in (registered.keys() | coordinators.keys()) - listed.keys():
            excluded = device_id in self.client.excluded_device_ids
            if (
                not excluded
                and self.client.home_graphs_without(device_id)
                < HOME_GRAPHS_BEFORE_REMOVAL
            ):
                continue
            if (device := registered.get(device_id)) is not None:
                _LOGGER.info(
                    "Removed %s, which is in a home whose devices aren't added"
                    if excluded
                    else "Removed %s, which Google no longer lists",
                    device.name_by_user or device.name,
                )
                registry.async_remove_device(device.id)
            self._asked.pop(device_id, None)
            if (coordinator := coordinators.pop(device_id, None)) is not None:
                await coordinator.async_shutdown()

    @callback
    def async_ask_to_sign_in_if_rejected(self) -> None:
        """Ask to sign in again while Google rejects the master token.

        Home Assistant ignores it while a sign-in is open.
        """
        if self.client.sign_in_error is not None:
            self.config_entry.async_start_reauth(self.hass)


class GoogleHomeDeviceCoordinator(DataUpdateCoordinator[GoogleHomeDevice | None]):
    """One device's alarms, timers and settings, or None while Google doesn't list it."""

    config_entry: GoogleHomeConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoogleHomeConfigEntry,
        client: GlocaltokensApiClient,
        device: GoogleHomeDevice,
        update_interval: timedelta | None,
    ) -> None:
        """Create the coordinator of a device that Google lists."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=device.name,
            update_interval=update_interval,
        )
        self.client = client
        self.device_id = device.device_id
        # The device and the known host where the account's lookup found it, so its info
        # just answered 200. Only its next poll uses it, and only for that device object
        # at that address.
        self.info_answered: tuple[GoogleHomeDevice, str] | None = None

    @override
    async def async_request_refresh(self) -> None:
        """Ask for an update, as an action or a refresh of the entity does.

        While polling is off, ask for an update of the account first, as nothing else
        updates it. It fetches Google's list when due or unknown, and starts a round in
        which a device that rejects its token can get a new one. Home Assistant runs
        one such update at a time: a request while it runs, such as for another device
        of the same refresh, doesn't wait for it.
        """
        if self.config_entry.pref_disable_polling:
            await self.config_entry.runtime_data.account.async_request_refresh()
        await super().async_request_refresh()

    def _listed(self) -> GoogleHomeDevice | None:
        """Return the device as Google's list has it now, if it does."""
        return next(
            (d for d in self.client.google_devices if d.device_id == self.device_id),
            None,
        )

    @override
    async def _async_update_data(self) -> GoogleHomeDevice | None:
        """Ask the device for its alarms, timers and settings, and firmware when due.

        Only if Google lists it. A fetch of Google's list while the device is asked
        may drop it, or replace it with a new object, so the old one isn't shown
        again.
        """
        answered, self.info_answered = self.info_answered, None
        if (device := self._listed()) is None:
            return None
        asked = await self.client.update_device(
            device, found_at_known_host=answered == (device, device.ip_address)
        )
        # Its token may have made Google's list be fetched, and Google reject the
        # master token
        self.config_entry.runtime_data.account.async_ask_to_sign_in_if_rejected()
        # Not for a device object that Google's list no longer has
        if asked and device is self._listed():
            await self.client.update_firmware(device)
        if device is not self._listed():
            return None
        self._async_show_firmware(device)
        return device

    @callback
    def _async_show_firmware(self, device: GoogleHomeDevice) -> None:
        """Show a change to the device's firmware version on its page in Home Assistant.

        Home Assistant reads an entity's device info, which has the version, only when
        it adds the entity, so a version that changes later is set here. An unknown
        version leaves the last one shown.
        """
        if (version := device.sw_version) is None:
            return
        registry = dr.async_get(self.hass)
        entry = registry.async_get_device_by_identifier(
            (DOMAIN, self.device_id), self.config_entry.entry_id
        )
        if entry is not None and entry.sw_version != version:
            registry.async_update_device(entry.id, sw_version=version)

    @callback
    def async_unlisted(self) -> None:
        """Show that Google no longer lists the device."""
        self.info_answered = None
        if self.data is not None:
            self.async_set_updated_data(None)
