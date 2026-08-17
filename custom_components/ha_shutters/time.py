"""Telework schedule controls for Solar Shutters."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_TELEWORK_END,
    CONF_TELEWORK_START,
    DEFAULT_TELEWORK_END,
    DEFAULT_TELEWORK_START,
    DOMAIN,
)
from .controller import ShutterController
from .entity import SolarShuttersGlobalEntity

TIMES = (
    (CONF_TELEWORK_START, "telework_start", DEFAULT_TELEWORK_START),
    (CONF_TELEWORK_END, "telework_end", DEFAULT_TELEWORK_END),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up telework time inputs."""
    controller: ShutterController = hass.data[DOMAIN][entry.entry_id]
    if not controller.is_global_owner:
        return
    async_add_entities(
        TeleworkTime(controller, key, translation_key, default)
        for key, translation_key, default in TIMES
    )


class TeleworkTime(SolarShuttersGlobalEntity, TimeEntity):
    """A persisted boundary of the telework time range."""

    def __init__(
        self,
        controller: ShutterController,
        key: str,
        translation_key: str,
        default: time,
    ) -> None:
        super().__init__(controller, key)
        self._key = key
        self._default = default
        self._attr_translation_key = translation_key
        self._attr_icon = "mdi:clock-outline"

    @property
    def native_value(self) -> time:
        return self.controller.get_time(self._key, self._default)

    async def async_set_value(self, value: time) -> None:
        await self.controller.async_update_setting(self._key, value.isoformat())
