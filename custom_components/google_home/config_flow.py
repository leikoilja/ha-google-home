"""Adds config flow for Google Home."""

from collections.abc import Mapping
import ipaddress
import logging
from typing import Self, cast, override

from glocaltokens.exceptions import AuthenticationError
from glocaltokens.utils.token import is_aas_et
import probatio
from requests.exceptions import HTTPError, RequestException

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
STEP_REAUTH = "reauth"

OAUTH_TOKEN_PREFIX = "oauth2_4/"

# Domains where Google ignores dots before the @, and which are the same accounts
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

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

    async def async_step_reauth(
        self, _entry_data: Mapping[str, object]
    ) -> ConfigFlowResult:
        """Ask how to sign in again when Google rejects the saved master token."""
        return self.async_show_menu(
            step_id=STEP_REAUTH,
            menu_options=[STEP_BROWSER, STEP_MASTER_TOKEN],
            description_placeholders={"name": self._get_reauth_entry().title},
        )

    async def async_step_reauth_browser(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Sign in again with the oauth_token cookie from a browser sign-in."""
        return await self.async_step_browser(user_input)

    async def async_step_reauth_master_token(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Sign in again with an existing master token."""
        return await self.async_step_master_token(user_input)

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
                    session=async_get_clientsession(self.hass),
                    oauth_token=oauth_token,
                    android_id=self._saved_android_id(),
                )
                # Getting the master token exchanges the cookie for it
                error = await self._sign_in(client, "oauth-token-invalid")
                if error is None:
                    username = await client.async_get_email() or ""
                    if not self._is_other_account(username):
                        self.username = username
                        return await self._create_entry(
                            client, username, username or BROWSER_TITLE
                        )
                    error = "other-account"
                errors["base"] = error
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
                    session=async_get_clientsession(self.hass),
                    username="",
                    password="",
                    master_token=master_token,
                    android_id=self._saved_android_id(),
                )
                error = await self._sign_in(client, "master-token-invalid")
                if error is None:
                    username = await client.async_get_email() or ""
                    if not self._is_other_account(username):
                        self.username = username
                        return await self._create_entry(
                            client, username, username or MASTER_TOKEN_TITLE
                        )
                    error = "other-account"
                errors["base"] = error
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
        """Save the master token that every sign-in method ends with.

        Signing in again saves it in the existing entry instead.
        """
        data = {
            CONF_MASTER_TOKEN: await client.async_get_master_token(),
            CONF_USERNAME: username,
            # Older versions saved an app password here
            CONF_PASSWORD: "",
            CONF_ANDROID_ID: await client.get_android_id(),
        }
        if self.source != SOURCE_REAUTH:
            return self.async_create_entry(title=title, data=data)
        entry = self._get_reauth_entry()
        # Keep the saved address when Google doesn't give one
        data[CONF_USERNAME] = username or entry.data.get(CONF_USERNAME, "")
        result = self.async_update_and_abort(entry, data_updates=data)
        # Not async_update_reload_and_abort(), which Home Assistant refuses from
        # 2026.12 for an entry with an update listener. This entry's listener reloads
        # it only when known hosts change, and an entry that failed setup has none.
        self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return result

    def _saved_android_id(self) -> str | None:
        """Return the entry's Android ID when signing in again, to save it unchanged.

        Without one, glocaltokens makes up a new Android ID.
        """
        if self.source != SOURCE_REAUTH:
            return None
        return cast(str | None, self._get_reauth_entry().data.get(CONF_ANDROID_ID))

    def _is_other_account(self, username: str) -> bool:
        """Return whether signing in again gives another account than the entry's.

        An address that Google doesn't give, or an entry without a known address,
        can't be compared, so it counts as the same account.
        """
        if self.source != SOURCE_REAUTH or not username:
            return False
        accounts = _get_accounts(self._get_reauth_entry())
        return bool(accounts) and _account_id(username) not in accounts

    def _show_form(
        self,
        step_id: str,
        schema: dict[probatio.Marker, type],
        errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Show the form of one sign-in method."""
        if self.source == SOURCE_REAUTH:
            # The same form, with text that doesn't suggest adding the integration
            # again: closing the window keeps the sign-in open
            step_id = f"{STEP_REAUTH}_{step_id}"
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
    async def _sign_in(client: GlocaltokensApiClient, rejected: str) -> str | None:
        """Return the form error saying why Google gives no master or access token.

        None means that Google gives both. rejected is the form's error for the cookie
        or master token that Google refuses.
        """
        try:
            await client.async_get_master_token()
            await client.async_get_access_token()
        except (InvalidMasterToken, RequestException) as error:
            # The form shows the error, so a traceback would only look like a bug
            _LOGGER.warning("Failed to sign in: %s", error)
            return _sign_in_error(error, rejected)
        return None


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
            description_placeholders={"default_interval": str(UPDATE_INTERVAL)},
        )


def _sign_in_error(error: InvalidMasterToken | RequestException, rejected: str) -> str:
    """Return the form error for why Google gave no master token or access token."""
    # glocaltokens raises HTTPError only when Google answers with a 5xx or 429
    if isinstance(error, HTTPError):
        return "google-busy"
    if isinstance(error, RequestException):
        return "google-unreachable"
    # Google refuses a used or expired cookie and a revoked master token with
    # BadAuthentication. Other reasons don't say that a new one would help.
    cause = error.__cause__
    if isinstance(cause, AuthenticationError) and cause.error == "BadAuthentication":
        return rejected
    return "google-rejected"


def _get_accounts(entry: GoogleHomeConfigEntry) -> set[str]:
    """Return the known email addresses of the entry's Google account.

    Older versions saved the address that the user typed, and gave master token
    entries a generic title, which has no @ until it's renamed after the address
    that Google gives.
    """
    return {
        _account_id(account)
        for account in (entry.data.get(CONF_USERNAME), entry.title)
        if account and "@" in account
    }


def _account_id(email: str) -> str:
    """Return an email address in a form that is the same for one Google account.

    Case doesn't matter, and Gmail addresses are the same with or without dots and
    with either domain.
    """
    local, _, domain = email.strip().casefold().rpartition("@")
    if domain in GMAIL_DOMAINS:
        return f"{local.replace('.', '')}@gmail.com"
    return f"{local}@{domain}"


def _is_ip_address(host: str) -> bool:
    """Return whether a known host is an IP address, which requests need."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
