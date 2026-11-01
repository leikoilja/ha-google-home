"""Adds config flow for Google Home."""

from collections.abc import Mapping
import ipaddress
import logging
from typing import cast, override

from glocaltokens.exceptions import AuthenticationError
from glocaltokens.utils.token import is_aas_et
import probatio
from requests.exceptions import HTTPError, RequestException

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import GlocaltokensApiClient
from .bluetooth import parse_irk, parse_mac
from .const import (
    BROWSER_TITLE,
    CONF_ANDROID_ID,
    CONF_BLUETOOTH_EXCLUDED,
    CONF_BLUETOOTH_TRACKING,
    CONF_EXCLUDED_HOMES,
    CONF_HOMES,
    CONF_IRK,
    CONF_IRK_OR_MAC,
    CONF_KNOWN_HOSTS,
    CONF_MASTER_TOKEN,
    CONF_OAUTH_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
    MASTER_TOKEN_TITLE,
    SUBENTRY_BLUETOOTH_DEVICE,
    UPDATE_INTERVAL,
)
from .exceptions import InvalidMasterToken
from .types import GoogleHomeConfigEntry, OptionsFlowDict

_LOGGER: logging.Logger = logging.getLogger(__package__)

STEP_BROWSER = "browser"
STEP_HOMES = "homes"
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
BLUETOOTH_DOCS_URL = "https://ha-google-home.pages.dev/bluetooth/"


class GoogleHomeFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1
    # 2: app passwords that older versions saved are cleared
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Start without an entry to create."""
        # The entry that the homes step creates, and the account's homes by ID, with
        # their names
        self._title = ""
        self._data: dict[str, str] = {}
        self._homes: dict[str, str] = {}

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
            homes = await client.async_get_homes()
            # Without a choice, or the homes, every home's devices are added
            if len(homes) > 1:
                self._title, self._data, self._homes = title, data, homes
                return await self.async_step_homes()
            return self.async_create_entry(title=title, data=data)
        entry = self._get_reauth_entry()
        # Keep the saved address when Google doesn't give one
        data[CONF_USERNAME] = username or entry.data.get(CONF_USERNAME, "")
        result = self.async_update_and_abort(entry, data_updates=data)
        # Not async_update_reload_and_abort(), which Home Assistant refuses from
        # 2026.12 for an entry with an update listener. This entry's listener reloads
        # it only when known hosts or homes change, and an entry that failed setup has
        # none.
        self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return result

    async def async_step_homes(
        self, user_input: dict[str, list[str]] | None = None
    ) -> ConfigFlowResult:
        """Choose the homes whose devices are added, when the account has several."""
        errors: dict[str, str] = {}
        selected = list(self._homes)
        if user_input is not None:
            selected = user_input[CONF_HOMES]
            if selected:
                excluded = sorted(self._homes.keys() - set(selected))
                return self.async_create_entry(
                    title=self._title,
                    data=self._data,
                    options={CONF_EXCLUDED_HOMES: excluded} if excluded else None,
                )
            errors[CONF_HOMES] = "no-home-selected"
        return self.async_show_form(
            step_id=STEP_HOMES,
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_HOMES, default=selected): _homes_selector(
                        self._homes
                    )
                }
            ),
            errors=errors,
        )

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

    def __init__(self) -> None:
        """Start without offering homes."""
        # The homes that the form offers, by ID, with their names. A home that the
        # integration finds while the form is open is neither offered nor excluded.
        self._homes: dict[str, str] = {}

    async def async_step_init(
        self, user_input: OptionsFlowDict | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        options: dict[str, object] = dict(self.config_entry.options)
        saved = set(cast(list[str], options.get(CONF_EXCLUDED_HOMES, [])))
        excluded = saved
        if user_input is not None:
            # Keep the order, which decides between hosts that report the same device
            known_hosts = list(
                dict.fromkeys(
                    host.strip()
                    for host in user_input.get(CONF_KNOWN_HOSTS, [])
                    if host.strip()
                )
            )
            if not all(_is_ip_address(host) for host in known_hosts):
                errors[CONF_KNOWN_HOSTS] = "known-host-not-ip"
            # A home that the form didn't offer keeps its choice
            offered = self._homes.keys()
            excluded = (saved - offered) | (
                offered - set(user_input.get(CONF_HOMES, []))
            )
            # Choosing no home is refused, unless none of them was added before
            if offered and offered <= excluded and not offered <= saved:
                errors[CONF_HOMES] = "no-home-selected"
            if not errors:
                data: dict[str, object] = {
                    **user_input,
                    CONF_KNOWN_HOSTS: known_hosts,
                }
                data.pop(CONF_HOMES, None)
                if excluded:
                    data[CONF_EXCLUDED_HOMES] = sorted(excluded)
                return self.async_create_entry(data=data)
            options = {**options, **user_input}

        entry = self.config_entry
        homes = (
            entry.runtime_data.client.homes
            if entry.state is ConfigEntryState.LOADED
            else {}
        )
        # Offer the homes when there's a choice, or a home to add again
        self._homes = dict(homes) if len(homes) > 1 or homes.keys() & excluded else {}
        schema: dict[probatio.Marker, object] = {
            probatio.Optional(
                CONF_UPDATE_INTERVAL,
                default=options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL),
            ): int,
            probatio.Optional(
                CONF_KNOWN_HOSTS,
                default=options.get(CONF_KNOWN_HOSTS, []),
            ): SelectSelector(
                SelectSelectorConfig(custom_value=True, options=[], multiple=True)
            ),
        }
        if self._homes:
            schema[
                probatio.Required(
                    CONF_HOMES,
                    default=[home for home in self._homes if home not in excluded],
                )
            ] = _homes_selector(self._homes)
        schema[
            probatio.Optional(
                CONF_BLUETOOTH_TRACKING,
                default=options.get(CONF_BLUETOOTH_TRACKING, False),
            )
        ] = bool
        schema[
            probatio.Optional(
                CONF_BLUETOOTH_EXCLUDED,
                default=options.get(CONF_BLUETOOTH_EXCLUDED, []),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=self._speaker_options(options.get(CONF_BLUETOOTH_EXCLUDED, [])),
                multiple=True,
            )
        )
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(schema),
            errors=errors,
            description_placeholders={"default_interval": str(UPDATE_INTERVAL)},
        )

    def _speaker_options(self, excluded: object) -> list[SelectOptionDict]:
        """Return the entry's speakers to choose from, by name.

        Excluded speakers that Google no longer lists stay, so saving the form
        doesn't silently drop them.
        """
        entry = self.config_entry
        devices = (
            entry.runtime_data.account.data or {}
            if entry.state is ConfigEntryState.LOADED
            else {}
        )
        names = {device_id: device.name for device_id, device in devices.items()}
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
        """Ask for the device's name, and its IRK or MAC address in one field.

        Which one it is shows from its form: a MAC address is six hex pairs, an IRK
        16 bytes. Either is saved as before, as an IRK or a MAC address.
        """
        entry = self._get_entry()
        if not entry.options.get(CONF_BLUETOOTH_TRACKING):
            return self.async_abort(reason="bluetooth-tracking-off")
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            value = user_input[CONF_IRK_OR_MAC].strip()
            data: dict[str, str] = {}
            if not name:
                errors[CONF_NAME] = "name-empty"
            elif not value:
                errors[CONF_IRK_OR_MAC] = "irk-or-mac"
            elif (address := parse_mac(value)) is not None:
                data = {CONF_MAC: address}
            elif (irk := parse_irk(value)) is not None:
                data = {CONF_IRK: irk.hex()}
            else:
                # Up to 17 characters, the length of a MAC address with separators,
                # was probably meant as one
                errors[CONF_IRK_OR_MAC] = (
                    "mac-invalid" if len(value) <= 17 else "irk-invalid"
                )
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
                        probatio.Required(CONF_IRK_OR_MAC): str,
                    }
                ),
                user_input,
            ),
            errors=errors,
            description_placeholders={"docs_url": BLUETOOTH_DOCS_URL},
        )


def _homes_selector(homes: Mapping[str, str]) -> SelectSelector:
    """Return a checkbox for each home, by name."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=home_id, label=name or home_id)
                for home_id, name in sorted(homes.items(), key=lambda home: home[1])
            ],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
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
