"""Adds config flow for Google Home"""
from __future__ import annotations

from datetime import timedelta
import logging

from requests.exceptions import RequestException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DOMAIN,
    MAX_PASSWORD_LENGTH,
    UPDATE_INTERVAL,
)
from .exceptions import InvalidMasterToken
from .types import ConfigFlowDict, OptionsFlowDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._errors: dict[str, str] = {}

    async def async_step_user(
        self, user_input: ConfigFlowDict | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            session = async_create_clientsession(self.hass)

            if len(password) < MAX_PASSWORD_LENGTH:
                client = GlocaltokensApiClient(
                    hass=self.hass,
                    session=session,
                    username=username,
                    password=password,
                )
                master_token = await self._test_credentials(client)
                if master_token is not None:
                    config_data: dict[str, str] = {}
                    config_data[CONF_USERNAME] = username
                    config_data[CONF_PASSWORD] = password
                    config_data[CONF_MASTER_TOKEN] = master_token
                    config_data[CONF_ANDROID_ID] = await client.get_android_id()
                    return self.async_create_entry(title=username, data=config_data)
                self._errors["base"] = "auth"
            else:
                self._errors["base"] = "pass-len"
        return await self._show_config_form()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> GoogleHomeOptionsFlowHandler:
        return GoogleHomeOptionsFlowHandler(config_entry)

    async def _show_config_form(self) -> FlowResult:
        """Show the configuration form to edit login information."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=self._errors,
        )

    @staticmethod
    async def _test_credentials(client: GlocaltokensApiClient) -> str | None:
        """Returns true and master token if credentials are valid."""
        try:
            master_token = await client.async_get_master_token()
            return master_token
        except (InvalidMasterToken, RequestException) as exception:
            _LOGGER.error(exception)
        return None


class GoogleHomeOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for GoogleHome."""

    def __init__(self, config_entry: ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
        # Cast from MappingProxy to dict to allow update.
        self.options = dict(config_entry.options)

    async def async_step_init(
        self, user_input: OptionsFlowDict | None = None
    ) -> FlowResult:
        """Manage the options."""
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
                }
            ),
        )
