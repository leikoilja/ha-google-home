"""Device tracker platform for Bluetooth devices that Google Home devices hear."""

from typing import override

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import BaseScannerEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .bluetooth import TrackerState
from .const import DATA_BLUETOOTH, DOMAIN, SUBENTRY_BLUETOOTH_DEVICE
from .types import GoogleHomeConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a tracker for each tracked Bluetooth device, if tracking is on."""
    coordinator: DataUpdateCoordinator[dict[str, TrackerState]] | None = hass.data[
        DOMAIN
    ][entry.entry_id].get(DATA_BLUETOOTH)
    if coordinator is None:
        return
    for subentry in entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE):
        async_add_entities(
            [GoogleHomeBluetoothTracker(coordinator, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class GoogleHomeBluetoothTracker(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, TrackerState]]],
    BaseScannerEntity,
):
    """Whether a tracked Bluetooth device is home, by what the speakers hear."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_source_type = SourceType.BLUETOOTH_LE

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, TrackerState]],
        subentry: ConfigSubentry,
    ) -> None:
        """Create the tracker of a tracked device."""
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._subentry_title = subentry.title
        self._attr_unique_id = subentry.subentry_id
        self._tracker_state = self._state_from_coordinator()

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Return the tracked device, named as the user named it."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._subentry_id)}, name=self._subentry_title
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether the speakers can tell if the device is home."""
        return super().available and self._tracker_state != TrackerState.UNAVAILABLE

    @property
    @override
    def is_connected(self) -> bool | None:
        """Return whether the device is home, or None while it's unknown."""
        if self._tracker_state == TrackerState.HOME:
            return True
        if self._tracker_state == TrackerState.NOT_HOME:
            return False
        return None

    def _state_from_coordinator(self) -> TrackerState:
        """Return the state of the latest update."""
        data = self.coordinator.data or {}
        return data.get(self._subentry_id, TrackerState.UNKNOWN)

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Write the state only when it changes, so history gets no row every update."""
        state = self._state_from_coordinator()
        if state == self._tracker_state:
            return
        self._tracker_state = state
        self.async_write_ha_state()
