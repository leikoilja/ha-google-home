"""Adds config flow for Google Home."""

import ipaddress
import logging
from typing import Self, override

from glocaltokens.utils.token import is_aas_et
import probatio
from requests.exceptions import RequestException

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import GlocaltokensApiClient
from .const import (
    BROWSER_TITLE,
    CONF_ANDROID_ID,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_OAUTH_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
    MASTER_TOKEN_TITLE,
    UPDATE_INTERVAL,
)
from .exceptions import InvalidMasterToken
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
                }
            ),
            errors=errors,
        )


def _is_ip_address(host: str) -> bool:
    """Return whether a known host is an IP address, which requests need."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
