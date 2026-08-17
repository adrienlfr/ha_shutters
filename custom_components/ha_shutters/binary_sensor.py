"""Diagnostic binary sensors for Solar Shutters."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import ShutterController
from .entity import SolarShuttersEntity


@dataclass(frozen=True, kw_only=True)
class DiagnosticDescription(BinarySensorEntityDescription):
    """Map a diagnostic sensor to a controller property."""

    attribute: str


DESCRIPTIONS = (
    DiagnosticDescription(
        key="sun_on_window",
        translation_key="sun_on_window",
        icon="mdi:white-balance-sunny",
        attribute="sun_on_window",
    ),
    DiagnosticDescription(
        key="automation_active",
        translation_key="automation_active",
        icon="mdi:robot",
        attribute="automation_active",
    ),
    DiagnosticDescription(
        key="shading_required",
        translation_key="shading_required",
        icon="mdi:window-shutter",
        attribute="shading_required",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensors."""
    controller: ShutterController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SolarShuttersBinarySensor(controller, description)
        for description in DESCRIPTIONS
    )


class SolarShuttersBinarySensor(SolarShuttersEntity, BinarySensorEntity):
    """Expose a controller decision as a binary sensor."""

    entity_description: DiagnosticDescription

    def __init__(
        self, controller: ShutterController, description: DiagnosticDescription
    ) -> None:
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.controller, self.entity_description.attribute))
