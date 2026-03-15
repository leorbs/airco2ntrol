import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

DOMAIN = "airco2ntrol"
PLATFORMS = ["sensor"]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up AirCO2ntrol from a config entry."""
    _LOGGER.info("Setting up AirCO2ntrol integration")

    hass.data.setdefault(DOMAIN, {})

    # Load sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload an AirCO2ntrol config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        reader = entry_data.get("reader")
        if reader is not None:
            await hass.async_add_executor_job(reader.close)

    return unload_ok
