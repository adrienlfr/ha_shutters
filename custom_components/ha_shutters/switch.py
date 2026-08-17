"""Switch controls for Solar Shutters."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DAWN_DUSK_AWAY,
    CONF_ENABLED,
    CONF_ONLY_AWAY,
    CONF_TELEWORK_ENABLED,
    DEFAULT_DAWN_DUSK_AWAY,
    DEFAULT_ENABLED,
    DEFAULT_ONLY_AWAY,
    DEFAULT_TELEWORK_ENABLED,
    DOMAIN,
)
from .controller import ShutterController
from .entity import SolarShuttersEntity


@dataclass(frozen=True, kw_only=True)
class SolarShuttersSwitchDescription(SwitchEntityDescription):
    """Describe a persisted boolean control."""

    default: bool


DESCRIPTIONS = (
    SolarShuttersSwitchDescription(
        key=CONF_ENABLED,
        translation_key="enabled",
        icon="mdi:window-shutter-auto",
        default=DEFAULT_ENABLED,
    ),
    SolarShuttersSwitchDescription(
        key=CONF_ONLY_AWAY,
        translation_key="only_away",
        icon="mdi:home-export-outline",
        default=DEFAULT_ONLY_AWAY,
    ),
    SolarShuttersSwitchDescription(
        key=CONF_TELEWORK_ENABLED,
        translation_key="telework_enabled",
        icon="mdi:laptop-account",
        default=DEFAULT_TELEWORK_ENABLED,
    ),
    SolarShuttersSwitchDescription(
        key=CONF_DAWN_DUSK_AWAY,
        translation_key="dawn_dusk_away",
        icon="mdi:theme-light-dark",
        default=DEFAULT_DAWN_DUSK_AWAY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for a window."""
    controller: ShutterController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SolarShuttersSwitch(controller, description) for description in DESCRIPTIONS
    )


class SolarShuttersSwitch(SolarShuttersEntity, SwitchEntity):
    """A persistent Solar Shutters switch."""

    entity_description: SolarShuttersSwitchDescription

    def __init__(
        self,
        controller: ShutterController,
        description: SolarShuttersSwitchDescription,
    ) -> None:
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.controller.get_bool(
            self.entity_description.key, self.entity_description.default
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.controller.async_update_setting(self.entity_description.key, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.controller.async_update_setting(self.entity_description.key, False)
