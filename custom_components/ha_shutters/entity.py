"""Base entity for Solar Shutters controls and diagnostics."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import ShutterController


class SolarShuttersEntity(Entity):
    """Base entity bound to a window controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: ShutterController, key: str) -> None:
        self.controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name=controller.entry.title,
            manufacturer="Solar Shutters",
            model="Window automation",
            configuration_url=(
                "homeassistant://config/integrations/integration/ha_shutters"
            ),
        )

    async def async_added_to_hass(self) -> None:
        """Register for controller changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.subscribe(self.async_write_ha_state))


class SolarShuttersGlobalEntity(Entity):
    """Base entity for behavior shared by every configured window."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: ShutterController, key: str) -> None:
        self.controller = controller
        self._attr_unique_id = f"global_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Solar Shutters",
            manufacturer="Solar Shutters",
            model="Global behavior",
            configuration_url=(
                "homeassistant://config/integrations/integration/ha_shutters"
            ),
        )

    async def async_added_to_hass(self) -> None:
        """Register for global controller changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.subscribe(self.async_write_ha_state))
