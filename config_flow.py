"""Config flow for AirCO2ntrol integration."""
import logging
import voluptuous as vol
from homeassistant import config_entries

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

class AirCO2ntrolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirCO2ntrol."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Create the config entry
            return self.async_create_entry(title="AirCO2ntrol", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            errors=errors,
        )
