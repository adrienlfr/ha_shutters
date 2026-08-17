"""Temperature threshold control for Solar Shutters."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_TEMPERATURE_THRESHOLD,
    DEFAULT_TEMPERATURE_THRESHOLD,
    DOMAIN,
)
from .controller import ShutterController
from .entity import SolarShuttersEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the threshold number."""
    controller: ShutterController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TemperatureThresholdNumber(controller)])


class TemperatureThresholdNumber(SolarShuttersEntity, NumberEntity):
    """Temperature from which direct sun causes the shutter to close."""

    _attr_translation_key = "temperature_threshold"
    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -10.0
    _attr_native_max_value = 50.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, controller: ShutterController) -> None:
        super().__init__(controller, CONF_TEMPERATURE_THRESHOLD)

    @property
    def native_value(self) -> float:
        return self.controller.get_float(
            CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.controller.async_update_setting(
            CONF_TEMPERATURE_THRESHOLD, float(value)
        )
