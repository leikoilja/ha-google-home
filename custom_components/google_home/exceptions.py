"""The errors of GoogleHome integration."""

from homeassistant.exceptions import HomeAssistantError


class InvalidMasterToken(HomeAssistantError):
    """Error to indicate the master token is invalid."""


class BluetoothScanError(HomeAssistantError):
    """Error to indicate a device didn't start a Bluetooth scan or return its results."""


class BluetoothScanUnsupported(BluetoothScanError):
    """Error to indicate a device has no Bluetooth scan endpoint."""
