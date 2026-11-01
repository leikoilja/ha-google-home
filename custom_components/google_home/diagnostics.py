"""Diagnostics of the integration, to attach to a bug report."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ANDROID_ID,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from .coordinator import GoogleAccountCoordinator, GoogleHomeDeviceCoordinator
from .types import GoogleHomeConfigEntry

# Credentials, tokens and addresses. Alarm and timer labels are kept.
TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MASTER_TOKEN,
    CONF_ANDROID_ID,
    CONF_KNOWN_HOSTS,
    "auth_token",
    "ip_address",
}


def _last_update(
    coordinator: GoogleAccountCoordinator | GoogleHomeDeviceCoordinator,
) -> dict[str, object]:
    """Return whether the coordinator's last update worked, and its last error's type.

    Not the error's text, which can include a device's address.
    """
    error = coordinator.last_exception
    return {
        "last_update_success": coordinator.last_update_success,
        "last_exception": type(error).__name__ if error is not None else None,
    }


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> dict[str, object]:
    """Return the entry's settings, and the state of the account and each device.

    Not the entry's title, which can be the account's email address.
    """
    data = entry.runtime_data
    # From Google's list, not the device's coordinator, whose data stays None after a
    # failed first update until one works. A device that Google no longer lists has
    # only how its last update went.
    listed = {device.device_id: device for device in data.client.google_devices}
    found = data.client.found_devices
    devices: dict[str, object] = {}
    for device_id, coordinator in data.devices.items():
        info = _last_update(coordinator)
        if (device := listed.get(device_id)) is not None:
            info |= {
                "name": device.name,
                "model": device.hardware,
                "ip_address": device.ip_address,
                "auth_token": device.auth_token,
                "available": device.available,
                "reachable": device.reachable,
                "alarms_unsupported": device.alarms_unsupported,
                "unanswered_updates": device.unanswered_updates,
                "statuses": {
                    f"{endpoint} ({'update' if polling else 'action'})": status
                    for (endpoint, polling), status in device.statuses.items()
                },
                "do_not_disturb": device.do_not_disturb,
                "alarm_volume": device.alarm_volume,
                "alarms_reply": device.alarms_reply,
                "build_info": device.build_info,
                "has_update": device.has_update,
                # Whether mDNS reported it since the integration loaded, or since a fetch
                # last dropped it from Google's list. None without Google's ID to match
                # a report to.
                "mdns_reported": (
                    found.get(device.cloud_device_id) is not None
                    if device.cloud_device_id
                    else None
                ),
            }
        devices[device_id] = info
    # How many Cast devices that mDNS reported since the integration loaded aren't in
    # Google's list, also those offline since. Those of excluded homes are in Google's
    # list, just not added. A fetch that drops a device from the list forgets its
    # reports. None until a fetch of the list has worked, even one that listed no
    # devices. A rejected token that marks the list to fetch again doesn't make it
    # unknown.
    not_listed = (
        len(
            found.cloud_device_ids
            - {d.cloud_device_id for d in listed.values()}
            - data.client.excluded_cloud_device_ids
        )
        if data.client.google_devices_fetched_once
        else None
    )
    return async_redact_data(
        {
            "now": dt_util.now().isoformat(),
            "data": dict(entry.data),
            "options": dict(entry.options),
            "account": _last_update(data.account)
            | {
                "google_devices_fetched": data.client.google_devices_fetched,
                "sign_in_rejected": data.client.sign_in_error is not None,
            },
            "mdns_reported_not_listed": not_listed,
            "devices": devices,
        },
        TO_REDACT,
    )
