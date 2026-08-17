"""Solar Shutters integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DAWN_DUSK_AWAY,
    CONF_ENABLED,
    CONF_ONLY_AWAY,
    CONF_TELEWORK_ENABLED,
    CONF_TELEWORK_END,
    CONF_TELEWORK_START,
    CONF_TEMPERATURE_THRESHOLD,
    DATA_GLOBAL_MANAGER,
    DOMAIN,
    PLATFORMS,
    STORAGE_VERSION,
)
from .controller import ShutterController
from .global_settings import GlobalSettingsManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solar Shutters from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = domain_data.get(DATA_GLOBAL_MANAGER)
    if manager is None:
        manager = domain_data[DATA_GLOBAL_MANAGER] = GlobalSettingsManager(hass)
    await manager.async_initialize(entry)

    controller = ShutterController(hass, entry, manager)
    manager.register(controller)
    await controller.async_setup()

    domain_data[entry.entry_id] = controller
    _remove_legacy_global_entities(hass, entry)
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
        manager: GlobalSettingsManager = hass.data[DOMAIN][DATA_GLOBAL_MANAGER]
        manager.unregister(entry.entry_id)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move global controls to another window when their owner is deleted."""
    domain_data = hass.data.get(DOMAIN)
    if not domain_data or DATA_GLOBAL_MANAGER not in domain_data:
        return
    manager: GlobalSettingsManager = domain_data[DATA_GLOBAL_MANAGER]
    new_owner_entry_id = manager.promote_after_removal(entry.entry_id)
    if new_owner_entry_id is None:
        await manager.async_clear()
        domain_data.pop(DATA_GLOBAL_MANAGER, None)
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
    if new_owner_entry_id is not None:
        # Run after Home Assistant clears entities belonging to the removed entry.
        hass.async_create_task(hass.config_entries.async_reload(new_owner_entry_id))


def _remove_legacy_global_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove per-window controls replaced by the single global device."""
    registry = er.async_get(hass)
    legacy_entities = {
        "switch": (
            CONF_ENABLED,
            CONF_ONLY_AWAY,
            CONF_TELEWORK_ENABLED,
            CONF_DAWN_DUSK_AWAY,
        ),
        "number": (CONF_TEMPERATURE_THRESHOLD,),
        "time": (CONF_TELEWORK_START, CONF_TELEWORK_END),
    }
    for platform, keys in legacy_entities.items():
        for key in keys:
            entity_id = registry.async_get_entity_id(
                platform, DOMAIN, f"{entry.entry_id}_{key}"
            )
            if entity_id is not None:
                registry.async_remove(entity_id)
