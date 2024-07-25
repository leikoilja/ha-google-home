"""Adds config flow for Google Home"""

from __future__ import annotations

from datetime import timedelta
import logging

from requests.exceptions import RequestException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GlocaltokensApiClient
from .const import (
    BT_UPDATE_INTERVAL,
    CONF_ANDROID_ID,
    CONF_BLUETOOTH,
    CONF_BT_UPDATE_INTERVAL,
    CONF_IRK,
    CONF_IRK_IDENTIFIER,
    CONF_MAC_IDENTIFIER,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DOMAIN,
    MANUFACTURER,
    MAX_PASSWORD_LENGTH,
    UPDATE_INTERVAL,
)
from .exceptions import InvalidMasterToken
from .types import ConfigFlowDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._errors: dict[str, str] = {}

    async def async_step_user(  # type: ignore
        self,
        user_input: ConfigFlowDict | None = None,  # type: ignore[override]
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            session = async_create_clientsession(self.hass)
            username = user_input.get(CONF_USERNAME, "")
            password = user_input.get(CONF_PASSWORD, "")
            master_token = user_input.get(CONF_MASTER_TOKEN, "")

            if master_token or (username and password):
                client = None
                title = username

                if master_token:
                    client = GlocaltokensApiClient(
                        hass=self.hass,
                        session=session,
                        username="",
                        password="",
                        master_token=master_token,
                    )
                    access_token = await self._get_access_token(client)
                    if access_token:
                        title = f"{MANUFACTURER} (master_token)"
                    else:
                        self._errors["base"] = "master-token-invalid"
                elif len(password) < MAX_PASSWORD_LENGTH:
                    client = GlocaltokensApiClient(
                        hass=self.hass,
                        session=session,
                        username=username,
                        password=password,
                    )
                    master_token = await self._get_master_token(client)
                    if not master_token:
                        self._errors["base"] = "auth"
                else:
                    self._errors["base"] = "pass-len"

                if client and not self._errors:
                    config_data: dict[str, str] = {}
                    config_data[CONF_MASTER_TOKEN] = master_token
                    config_data[CONF_USERNAME] = username
                    config_data[CONF_PASSWORD] = password
                    config_data[CONF_ANDROID_ID] = await client.get_android_id()
                    return self.async_create_entry(title=title, data=config_data)
            else:
                self._errors["base"] = "missing-inputs"
        return await self._show_config_form()

    @staticmethod
    @callback
    def async_get_options_flow(  # type: ignore
        config_entry: ConfigEntry,
    ) -> GoogleHomeOptionsFlowHandler:
        return GoogleHomeOptionsFlowHandler(config_entry)

    async def _show_config_form(self) -> FlowResult:
        """Show the configuration form to edit login information."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_MASTER_TOKEN): str,
                }
            ),
            errors=self._errors,
        )

    @staticmethod
    async def _get_master_token(client: GlocaltokensApiClient) -> str:
        """Returns master token if credentials are valid."""
        master_token = ""
        try:
            master_token = await client.async_get_master_token()
        except (InvalidMasterToken, RequestException) as exception:
            _LOGGER.error(exception)
        return master_token

    @staticmethod
    async def _get_access_token(client: GlocaltokensApiClient) -> str:
        """Returns access token if master token is valid."""
        access_token = ""
        try:
            access_token = await client.async_get_access_token()
        except (InvalidMasterToken, RequestException) as exception:
            _LOGGER.error(exception)
        return access_token


class GoogleHomeOptionsFlowHandler(OptionsFlowWithConfigEntry):
    """Config flow options handler for GoogleHome."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # pylint: disable=unused-argument
    ) -> FlowResult:
        """Manage the options."""
        return self.async_show_menu(
            step_id="init", menu_options=["global", "bluetooth"]
        )

    async def async_step_global(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Manage the global options."""
        if user_input is not None:
            self.options.update(user_input)
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id][
                DATA_COORDINATOR
            ]
            update_interval = timedelta(
                seconds=self.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
            )
            _LOGGER.debug("Updating coordinator, update_interval: %s", update_interval)
            coordinator.update_interval = update_interval
            return self.async_create_entry(
                title=self.config_entry.data.get(CONF_USERNAME), data=self.options
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, UPDATE_INTERVAL
                        ),
                    ): int,
                    vol.Optional(
                        CONF_BT_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_BT_UPDATE_INTERVAL, BT_UPDATE_INTERVAL
                        ),
                    ): int,
                }
            ),
        )

    async def async_step_bluetooth(
        self,
        user_input: dict[str, str] | None = None,  # pylint: disable=unused-argument
    ) -> FlowResult:
        """Manage the options."""
        return self.async_show_menu(
            step_id="bluetooth",
            menu_options=["add_irk", "add_mac", "remove_irk", "remove_mac"],
        )

    async def async_step_add_irk(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            irk_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_IRK, [])
            mac_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_MAC, [])
            irk_list.append(user_input)
            self.options[CONF_BLUETOOTH] = {CONF_IRK: irk_list, CONF_MAC: mac_list}
            return self.async_create_entry(
                title=self.config_entry.data.get(CONF_USERNAME), data=self.options
            )

        return self.async_show_form(
            step_id="add_irk",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IRK_IDENTIFIER): str,
                    vol.Required(CONF_IRK): str,
                }
            ),
        )

    async def async_step_add_mac(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            irk_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_IRK, [])
            mac_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_MAC, [])
            mac_list.append(user_input)
            self.options[CONF_BLUETOOTH] = {CONF_IRK: irk_list, CONF_MAC: mac_list}
            return self.async_create_entry(
                title=self.config_entry.data.get(CONF_USERNAME), data=self.options
            )

        return self.async_show_form(
            step_id="add_mac",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC_IDENTIFIER): str,
                    vol.Required(CONF_MAC): str,
                }
            ),
        )

    async def async_step_remove_mac(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Manage the removal of MAC addresses."""
        if user_input is not None:
            mac_to_remove = user_input.get(CONF_MAC_IDENTIFIER)
            if mac_to_remove:
                # Retrieve current MAC list and remove the selected MAC address
                mac_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_MAC, [])
                mac_list = [
                    mac
                    for mac in mac_list
                    if mac.get(CONF_MAC_IDENTIFIER) != mac_to_remove
                ]
                self.options[CONF_BLUETOOTH] = {
                    CONF_IRK: self.options.get(CONF_BLUETOOTH, {}).get(CONF_IRK, []),
                    CONF_MAC: mac_list,
                }
                return self.async_create_entry(
                    title=self.config_entry.data.get(CONF_USERNAME), data=self.options
                )

        # Prepare list of current MAC addresses
        mac_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_MAC, [])
        mac_identifiers = [mac.get(CONF_MAC_IDENTIFIER) for mac in mac_list]

        return self.async_show_form(
            step_id="remove_mac",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC_IDENTIFIER): vol.In(mac_identifiers),
                }
            ),
        )

    async def async_step_remove_irk(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Manage the removal of irk addresses."""
        if user_input is not None:
            irk_to_remove = user_input.get(CONF_IRK_IDENTIFIER)
            if irk_to_remove:
                # Retrieve current MAC list and remove the selected MAC address
                irk_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_IRK, [])
                irk_list = [
                    irk
                    for irk in irk_list
                    if irk.get(CONF_IRK_IDENTIFIER) != irk_to_remove
                ]
                self.options[CONF_BLUETOOTH] = {
                    CONF_IRK: irk_list,
                    CONF_MAC: self.options.get(CONF_BLUETOOTH, {}).get(CONF_MAC, []),
                }
                return self.async_create_entry(
                    title=self.config_entry.data.get(CONF_USERNAME), data=self.options
                )

        # Prepare list of current irk addresses
        irk_list = self.options.get(CONF_BLUETOOTH, {}).get(CONF_IRK, [])
        irk_identifiers = [irk.get(CONF_IRK_IDENTIFIER) for irk in irk_list]

        return self.async_show_form(
            step_id="remove_irk",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IRK_IDENTIFIER): vol.In(irk_identifiers),
                }
            ),
        )
