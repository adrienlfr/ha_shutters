"""Solar Shutters integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .controller import ShutterController


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solar Shutters from a config entry."""
    controller = ShutterController(hass, entry)
    await controller.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply UI entity and options-flow changes without reloading platforms."""
    controller: ShutterController = hass.data[DOMAIN][entry.entry_id]
    await controller.async_settings_updated()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        controller: ShutterController = hass.data[DOMAIN].pop(entry.entry_id)
        await controller.async_shutdown()
    return unloaded
