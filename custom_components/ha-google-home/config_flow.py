"""Adds config flow for Google Home"""

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GlocaltokensApiClient
from .const import CONF_ANDROID_ID
from .const import CONF_MASTER_TOKEN
from .const import CONF_PASSWORD
from .const import CONF_USERNAME
from .const import DOMAIN
from .const import PLATFORMS


_LOGGER: logging.Logger = logging.getLogger(__package__)


class GoogleHomeFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for GoogleHome."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            session = async_create_clientsession(self.hass)
            client = GlocaltokensApiClient(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                session,
                None,
            )
            valid, master_token = await self._test_credentials(client)
            if valid:
                data = user_input
                data.update(
                    {
                        CONF_MASTER_TOKEN: master_token,
                        CONF_ANDROID_ID: await client.get_android_id(),
                    }
                )
                return self.async_create_entry(title=username, data=user_input)
            else:
                self._errors["base"] = "auth"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GoogleHomeOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=self._errors,
        )

    async def _test_credentials(self, client):
        """Returns true and master token if credentials are valid."""
        try:
            master_token = await client.async_get_master_token()
            return True, master_token
        except Exception as exception:
            _LOGGER.error(exception)
        return False, None


class GoogleHomeOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for GoogleHome."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(x, default=self.options.get(x, True)): bool
                    for x in sorted(PLATFORMS)
                }
            ),
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(
            title=self.config_entry.data.get(CONF_USERNAME), data=self.options
        )
