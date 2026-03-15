"""Config flow for AirCO2ntrol integration."""
import logging
import os
import voluptuous as vol
from homeassistant import config_entries

from . import DOMAIN
from .sensor import get_device_path

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_PATH = "device_path"


def _validate_device_path(device_path):
    """Validate that the given device path exists and is a character device."""
    if not os.path.exists(device_path):
        raise vol.Invalid("Device path does not exist: %s" % device_path)
    if not os.stat(device_path).st_mode & 0o020000:
        raise vol.Invalid("Not a character device: %s" % device_path)
    return device_path


class AirCO2ntrolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirCO2ntrol."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            custom_path = user_input.get(CONF_DEVICE_PATH, "").strip()

            if custom_path:
                # User provided a custom device path
                try:
                    await self.hass.async_add_executor_job(
                        _validate_device_path, custom_path
                    )
                except vol.Invalid:
                    errors[CONF_DEVICE_PATH] = "device_not_found"
                else:
                    # Try to get unique_id via auto-discovery for dedup
                    unique_id = None
                    try:
                        _, unique_id = await self.hass.async_add_executor_job(
                            get_device_path
                        )
                    except Exception:
                        pass

                    if unique_id:
                        await self.async_set_unique_id(unique_id)
                        self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="AirCO2ntrol",
                        data={CONF_DEVICE_PATH: custom_path},
                    )
            else:
                # Auto-discover
                try:
                    device_path, unique_id = await self.hass.async_add_executor_job(
                        get_device_path
                    )
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    if unique_id:
                        await self.async_set_unique_id(unique_id)
                        self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="AirCO2ntrol",
                        data={CONF_DEVICE_PATH: device_path},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEVICE_PATH, default=""): str,
            }),
            errors=errors,
        )
