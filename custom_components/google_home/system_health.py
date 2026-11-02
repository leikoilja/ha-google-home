"""The integration's section in Home Assistant's System information."""

from datetime import timedelta

from glocaltokens.const import GOOGLE_HOME_FOYER_API
import gpsoauth

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import CONF_BLUETOOTH_TRACKING, DOMAIN, UNANSWERED_UPDATES
from .coordinator import async_device_disabled
from .types import GoogleHomeConfigEntry

TROUBLESHOOTING_URL = "https://ha-google-home.pages.dev/troubleshooting/"
# Where the integration gets the device list from, over gRPC
DEVICE_LIST_URL = f"https://{GOOGLE_HOME_FOYER_API.removesuffix(':443')}/"


@callback
def async_register(
    _hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register the section, with a link to the integration's page."""
    register.async_register_info(
        system_health_info, f"/config/integrations/integration/{DOMAIN}"
    )


async def system_health_info(hass: HomeAssistant) -> dict[str, object]:
    """Return whether Google answers, and while the entry is loaded, the state of its devices.

    Each check is a plain web request, which any answer passes: it doesn't sign in or
    get the list. Only fixed states, the options, a time and counts follow, nothing
    that names the account, a home or a device, or gives an address or an error's text.
    Without a loaded entry, there's nothing to read: its page says why setup failed.
    """
    reach_help = f"{TROUBLESHOOTING_URL}#couldnt-reach-google"
    info: dict[str, object] = {
        "can_reach_sign_in": system_health.async_check_can_reach_url(
            hass, gpsoauth.AUTH_URL, reach_help
        ),
        "can_reach_device_list": system_health.async_check_can_reach_url(
            hass, DEVICE_LIST_URL, reach_help
        ),
    }
    entries: list[GoogleHomeConfigEntry] = hass.config_entries.async_loaded_entries(
        DOMAIN
    )
    if not entries:
        return info
    entry = entries[0]
    client = entry.runtime_data.client
    # Google rejected the master token during an earlier fetch, and no fetch has
    # worked since. Not what the latest fetch got, which may have been a server error.
    if client.sign_in_error is not None:
        info["device_list"] = {
            "type": "failed",
            "error": "sign-in rejected",
            "more_info": f"{TROUBLESHOOTING_URL}#sign-in-again",
        }
    else:
        info["device_list"] = (
            "fetched" if client.google_devices_fetched else "not fetched"
        )
    # The earliest the list is fetched again, at an update after that
    if wait := client.fetch_wait_left():
        info["retry_not_before"] = dt_util.utcnow() + timedelta(seconds=wait)
    info["polling"] = not entry.pref_disable_polling
    info["bluetooth_tracking"] = bool(entry.options.get(CONF_BLUETOOTH_TRACKING, False))
    # Until a fetch has worked, there's no list to count, not an empty one
    if client.google_devices_fetched_once:
        devices = client.google_devices
        info["devices_listed"] = len(devices)
        # A device without an address isn't asked. One that missed enough updates in
        # a row counts until it answers, also while it answers "not found" as it starts.
        # A disabled device isn't asked either, so it doesn't count.
        info["devices_not_answering"] = sum(
            (not device.ip_address or device.unanswered_updates >= UNANSWERED_UPDATES)
            and not async_device_disabled(hass, entry, device.device_id)
            for device in devices
        )
    return info
