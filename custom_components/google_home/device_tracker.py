"""Device tracker platform for Bluetooth devices that Google Home devices hear."""

from typing import override

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import BaseScannerEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .bluetooth import TrackerState, TrackerUpdate
from .const import DOMAIN, SUBENTRY_BLUETOOTH_DEVICE
from .types import GoogleHomeConfigEntry

# The Bluetooth coordinator does the updates, and trackers have no actions
PARALLEL_UPDATES = 0

ATTR_SPEAKERS = "speakers"


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a tracker for each tracked Bluetooth device, if tracking is on."""
    if (coordinator := entry.runtime_data.bluetooth) is None:
        return
    for subentry in entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE):
        async_add_entities(
            [GoogleHomeBluetoothTracker(coordinator, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class GoogleHomeBluetoothTracker(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, TrackerUpdate]]],
    BaseScannerEntity,
):
    """Whether a tracked Bluetooth device is home, by what the speakers hear."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_source_type = SourceType.BLUETOOTH_LE
    # Left out of history: it changes every few minutes, and only its current
    # value is useful
    _unrecorded_attributes = frozenset({ATTR_SPEAKERS})

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, TrackerUpdate]],
        subentry: ConfigSubentry,
    ) -> None:
        """Create the tracker of a tracked device."""
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._subentry_title = subentry.title
        self._attr_unique_id = subentry.subentry_id

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
        return (
            super().available and self._tracker_update.state != TrackerState.UNAVAILABLE
        )

    @property
    @override
    def is_connected(self) -> bool | None:
        """Return whether the device is home, or None while it's unknown."""
        state = self._tracker_update.state
        if state == TrackerState.HOME:
            return True
        if state == TrackerState.NOT_HOME:
            return False
        return None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, dict[str, int]]:
        """Return each speaker's median RSSI over the latest completed window."""
        return {ATTR_SPEAKERS: self._tracker_update.speakers}

    @property
    def _tracker_update(self) -> TrackerUpdate:
        """Return the latest update.

        Each update writes it, and Home Assistant adds no history row while the
        state and attributes stay the same.
        """
        data = self.coordinator.data or {}
        return data.get(self._subentry_id, TrackerUpdate(TrackerState.UNKNOWN, {}))
