"""Bluetooth support for Ruuvi Gateway."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    MONOTONIC_TIME,
    BaseHaRemoteScanner,
    async_register_scanner,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .models import GoogleHomeDevice

_LOGGER = logging.getLogger(__name__)


class GoogleHomeScanner(BaseHaRemoteScanner):
    """Scanner for Google Home."""

    def __init__(
        self,
        scanner_id: str,
        name: str,
        coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]],
    ) -> None:
        """Initialize the scanner, using the given update coordinator as data source."""
        super().__init__(
            scanner_id,
            name,
            connector=None,
            connectable=False,
        )
        self.coordinator = coordinator
        self._values: dict[str, tuple[float, float]] = {}

    @callback
    def _async_handle_new_data(self) -> None:
        monotonic_now = MONOTONIC_TIME()
        cur_device = [
            device
            for device in self.coordinator.data
            if device.mac.upper() == self.source
        ][0]
        for bt_device in cur_device.bt_devices.values():
            if (
                bt_device.mac_address not in self._values
                or bt_device.rssi != self._values[bt_device.mac_address][1]
            ):
                self._values[bt_device.mac_address] = (monotonic_now, bt_device.rssi)
                self._async_on_advertisement(
                    address=bt_device.mac_address.upper(),
                    rssi=bt_device.rssi,
                    local_name=bt_device.name,
                    service_data={},
                    service_uuids=[],
                    manufacturer_data={},
                    tx_power=None,
                    details={},
                    advertisement_monotonic_time=self._values[bt_device.mac_address][0],
                )

    @callback
    def start_polling(self) -> CALLBACK_TYPE:
        """Start polling; return a callback to stop polling."""
        return self.coordinator.async_add_listener(self._async_handle_new_data)


def async_connect_scanner(
    hass: HomeAssistant,
    coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]],
) -> tuple[list[GoogleHomeScanner], CALLBACK_TYPE]:
    """Connect scanner and start polling."""
    scanners = [
        GoogleHomeScanner(
            scanner_id=device.mac.upper(), name=device.name, coordinator=coordinator
        )
        for device in coordinator.data
    ]
    unload_callbacks = [
        [
            async_register_scanner(hass, scanner),
            scanner.async_setup(),
            scanner.start_polling(),
        ]
        for scanner in scanners
    ]

    @callback
    def _async_unload() -> None:
        for unloader in unload_callbacks:
            for scanner_unloader in unloader:
                scanner_unloader()

    return (scanners, _async_unload)
