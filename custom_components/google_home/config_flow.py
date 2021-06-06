"""Adds config flow for Google Home"""
from __future__ import annotations

import logging
from typing import Any

from requests.exceptions import RequestException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GlocaltokensApiClient
from .const import (
    CONF_ANDROID_ID,
    CONF_DATA_COLLECTION,
    CONF_MASTER_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from .exceptions import InvalidMasterToken
from .types import OptionsFlowDict

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize."""
        self._errors: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            session = async_create_clientsession(self.hass)
            client = GlocaltokensApiClient(
                hass=self.hass,
                session=session,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            master_token = await self._test_credentials(client)
            if master_token is not None:
                user_input[CONF_MASTER_TOKEN] = master_token
                user_input[CONF_ANDROID_ID] = await client.get_android_id()
                return self.async_create_entry(title=username, data=user_input)
            self._errors["base"] = "auth"
        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> GoogleHomeOptionsFlowHandler:
        return GoogleHomeOptionsFlowHandler(config_entry)

    async def _show_config_form(
        self, _user_input: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Show the configuration form to edit location data."""
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
    ) -> dict[str, Any]:
        """Manage the options."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DATA_COLLECTION,
                        default=self.config_entry.options.get(
                            CONF_DATA_COLLECTION, True
                        ),
                    ): bool,
                }
            ),
        )
