"""Adds config flow for Google Home."""

import ipaddress
import logging
from typing import Self, override

from glocaltokens.utils.token import is_aas_et
import probatio
from requests.exceptions import RequestException

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import GlocaltokensApiClient
from .bluetooth import normalize_mac, parse_irk
from .const import (
    BROWSER_TITLE,
    CONF_ANDROID_ID,
    CONF_BLUETOOTH_EXCLUDED,
    CONF_BLUETOOTH_TRACKING,
    CONF_IRK,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_OAUTH_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DOMAIN,
    MASTER_TOKEN_TITLE,
    SUBENTRY_BLUETOOTH_DEVICE,
    UPDATE_INTERVAL,
)
from .exceptions import InvalidMasterToken
from .models import GoogleHomeDevice
from .types import GoogleHomeConfigEntry, OptionsFlowDict

_LOGGER: logging.Logger = logging.getLogger(__package__)

STEP_BROWSER = "browser"
STEP_MASTER_TOKEN = "master_token"

OAUTH_TOKEN_PREFIX = "oauth2_4/"

DESCRIPTION_PLACEHOLDERS = {
    "docs_url": "https://ha-google-home.pages.dev/installation/",
    "browser_docs_url": "https://ha-google-home.pages.dev/installation/#browser-sign-in",
    "embedded_setup_url": "https://accounts.google.com/EmbeddedSetup",
}
BLUETOOTH_DOCS_URL = "https://ha-google-home.pages.dev/bluetooth/"


class GoogleHomeFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1
    # 2: app passwords that older versions saved are cleared
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize."""
        self.username: str | None = None

    @override
    def is_matching(self, other_flow: Self) -> bool:
        """Return True if other_flow is matching this flow."""
        return other_flow.username == self.username

    @override
    async def async_step_user(
        self,
        user_input: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Ask how to sign in."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[STEP_BROWSER, STEP_MASTER_TOKEN],
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )

    async def async_step_browser(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Sign in with the oauth_token cookie from a browser sign-in."""
        errors: dict[str, str] = {}
        if user_input is not None:
            oauth_token = user_input[CONF_OAUTH_TOKEN].strip()
            if not oauth_token.startswith(OAUTH_TOKEN_PREFIX):
                errors[CONF_OAUTH_TOKEN] = "oauth-token-format"
            else:
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=async_create_clientsession(self.hass),
                    oauth_token=oauth_token,
                )
                # Getting the master token exchanges the cookie for it
                if await self._sign_in(client):
                    username = await client.async_get_email() or ""
                    self.username = username
                    return await self._create_entry(
                        client, username, username or BROWSER_TITLE
                    )
                errors["base"] = "oauth-token-invalid"
        return self._show_form(
            STEP_BROWSER,
            {probatio.Required(CONF_OAUTH_TOKEN): str},
            errors,
        )

    async def async_step_master_token(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Sign in with an existing master token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            master_token = user_input[CONF_MASTER_TOKEN].strip()
            if not is_aas_et(master_token):
                errors[CONF_MASTER_TOKEN] = "master-token-format"
            else:
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=async_create_clientsession(self.hass),
                    username="",
                    password="",
                    master_token=master_token,
                )
                if await self._sign_in(client):
                    username = await client.async_get_email() or ""
                    self.username = username
                    return await self._create_entry(
                        client, username, username or MASTER_TOKEN_TITLE
                    )
                errors["base"] = "master-token-invalid"
        return self._show_form(
            STEP_MASTER_TOKEN,
            {probatio.Required(CONF_MASTER_TOKEN): str},
            errors,
        )

    async def _create_entry(
        self,
        client: GlocaltokensApiClient,
        username: str,
        title: str,
    ) -> ConfigFlowResult:
        """Save the master token that every sign-in method ends with."""
        return self.async_create_entry(
            title=title,
            data={
                CONF_MASTER_TOKEN: await client.async_get_master_token(),
                CONF_USERNAME: username,
                # Older versions saved an app password here
                CONF_PASSWORD: "",
                CONF_ANDROID_ID: await client.get_android_id(),
            },
        )

    def _show_form(
        self,
        step_id: str,
        schema: dict[probatio.Marker, type],
        errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Show the form of one sign-in method."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=probatio.Schema(schema),
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: GoogleHomeConfigEntry,
    ) -> GoogleHomeOptionsFlowHandler:
        """Handle options flow."""
        return GoogleHomeOptionsFlowHandler()

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(  # type: ignore[explicit-any]
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentries this integration supports.

        Always offered: Home Assistant keeps this until it restarts, so it
        wouldn't follow the Bluetooth tracking option.
        """
        return {SUBENTRY_BLUETOOTH_DEVICE: BluetoothDeviceSubentryFlow}

    @staticmethod
    async def _sign_in(client: GlocaltokensApiClient) -> bool:
        """Return whether Google gives a master token and an access token."""
        try:
            await client.async_get_master_token()
            await client.async_get_access_token()
        except InvalidMasterToken, RequestException:
            _LOGGER.exception("Failed to sign in")
            return False
        return True


class GoogleHomeOptionsFlowHandler(OptionsFlow):
    """Config flow options handler for GoogleHome."""

    async def async_step_init(
        self, user_input: OptionsFlowDict | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        options: dict[str, object] = dict(self.config_entry.options)
        if user_input is not None:
            # Keep the order, which decides between hosts that report the same device
            known_hosts = list(
                dict.fromkeys(
                    host.strip()
                    for host in user_input.get(CONF_KNOWN_HOSTS, [])
                    if host.strip()
                )
            )
            if all(_is_ip_address(host) for host in known_hosts):
                return self.async_create_entry(
                    data={**user_input, CONF_KNOWN_HOSTS: known_hosts}
                )
            errors[CONF_KNOWN_HOSTS] = "known-host-not-ip"
            options = {**options, **user_input}

        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL),
                    ): int,
                    probatio.Optional(
                        CONF_KNOWN_HOSTS,
                        default=options.get(CONF_KNOWN_HOSTS, []),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            custom_value=True, options=[], multiple=True
                        )
                    ),
                    probatio.Optional(
                        CONF_BLUETOOTH_TRACKING,
                        default=options.get(CONF_BLUETOOTH_TRACKING, False),
                    ): bool,
                    probatio.Optional(
                        CONF_BLUETOOTH_EXCLUDED,
                        default=options.get(CONF_BLUETOOTH_EXCLUDED, []),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=self._speaker_options(
                                options.get(CONF_BLUETOOTH_EXCLUDED, [])
                            ),
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    def _speaker_options(self, excluded: object) -> list[SelectOptionDict]:
        """Return the entry's speakers to choose from, by name.

        Excluded speakers that Google no longer lists stay, so saving the form
        doesn't silently drop them.
        """
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        coordinator: DataUpdateCoordinator[list[GoogleHomeDevice]] | None = (
            entry_data[DATA_COORDINATOR] if entry_data else None
        )
        names = {
            device.device_id: device.name
            for device in (coordinator.data if coordinator else None) or []
        }
        for device_id in excluded if isinstance(excluded, list) else []:
            names.setdefault(str(device_id), str(device_id))
        return [
            SelectOptionDict(value=device_id, label=name)
            for device_id, name in sorted(
                names.items(), key=lambda item: item[1].casefold()
            )
        ]


class BluetoothDeviceSubentryFlow(ConfigSubentryFlow):
    """Add a Bluetooth device for the speakers to track."""

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> SubentryFlowResult:
        """Ask for the device's name and its IRK or MAC address."""
        entry = self._get_entry()
        if not entry.options.get(CONF_BLUETOOTH_TRACKING):
            return self.async_abort(reason="bluetooth-tracking-off")
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            irk = user_input.get(CONF_IRK, "").strip()
            mac = user_input.get(CONF_MAC, "").strip()
            data: dict[str, str] = {}
            if not name:
                errors[CONF_NAME] = "name-empty"
            elif bool(irk) == bool(mac):
                errors["base"] = "irk-or-mac"
            elif irk:
                if (irk_bytes := parse_irk(irk)) is None:
                    errors[CONF_IRK] = "irk-invalid"
                else:
                    data = {CONF_IRK: irk_bytes.hex()}
            elif (address := normalize_mac(mac)) is None:
                errors[CONF_MAC] = "mac-invalid"
            else:
                data = {CONF_MAC: address}
            if data and any(
                subentry.data == data
                for subentry in entry.get_subentries_of_type(SUBENTRY_BLUETOOTH_DEVICE)
            ):
                errors["base"] = "already-tracked"
            elif data:
                return self.async_create_entry(title=name, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_NAME): str,
                        probatio.Optional(CONF_IRK): str,
                        probatio.Optional(CONF_MAC): str,
                    }
                ),
                user_input,
            ),
            errors=errors,
            description_placeholders={"docs_url": BLUETOOTH_DOCS_URL},
        )


def _is_ip_address(host: str) -> bool:
    """Return whether a known host is an IP address, which requests need."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
