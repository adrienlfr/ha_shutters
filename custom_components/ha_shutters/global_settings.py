"""Shared behavior settings for all Solar Shutters windows."""

from __future__ import annotations

import asyncio
from datetime import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_GLOBAL_SETTINGS,
    DOMAIN,
    GLOBAL_SETTING_KEYS,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from .controller import ShutterController


class GlobalSettingsManager:
    """Persist and distribute one behavior configuration to every window."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.settings: dict[str, Any] = dict(DEFAULT_GLOBAL_SETTINGS)
        self.controllers: dict[str, ShutterController] = {}
        self.owner_entry_id: str | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.global_settings")
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def async_initialize(self, entry: ConfigEntry) -> None:
        """Load global settings once, importing legacy per-window values."""
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            stored = await self._store.async_load()
            if stored:
                self.settings.update(
                    {key: stored[key] for key in GLOBAL_SETTING_KEYS if key in stored}
                )
            else:
                legacy_settings = {**entry.data, **entry.options}
                self.settings.update(
                    {
                        key: self._serializable(legacy_settings[key])
                        for key in GLOBAL_SETTING_KEYS
                        if key in legacy_settings
                    }
                )
                await self._store.async_save(self.settings)
            self._initialized = True

    def register(self, controller: ShutterController) -> None:
        """Register a window and elect the first one to host global entities."""
        entry_id = controller.entry.entry_id
        self.controllers[entry_id] = controller
        if self.owner_entry_id is None:
            self.owner_entry_id = entry_id

    def unregister(self, entry_id: str) -> None:
        """Unregister a window."""
        self.controllers.pop(entry_id, None)

    def promote_after_removal(self, entry_id: str) -> str | None:
        """Elect another loaded window after the global owner is deleted."""
        if self.owner_entry_id == entry_id:
            self.owner_entry_id = next(iter(self.controllers), None)
        return self.owner_entry_id

    def is_owner(self, entry_id: str) -> bool:
        """Return whether an entry hosts the single set of global entities."""
        return self.owner_entry_id == entry_id

    async def async_update(self, key: str, value: Any) -> None:
        """Persist a global setting and immediately update every window."""
        if key not in GLOBAL_SETTING_KEYS:
            raise ValueError(f"Unsupported global setting: {key}")
        self.settings[key] = self._serializable(value)
        await self._store.async_save(self.settings)
        for controller in list(self.controllers.values()):
            await controller.async_global_settings_updated()

    async def async_clear(self) -> None:
        """Remove persisted globals after the last window is deleted."""
        await self._store.async_remove()

    @staticmethod
    def _serializable(value: Any) -> Any:
        if isinstance(value, time):
            return value.isoformat()
        return value
