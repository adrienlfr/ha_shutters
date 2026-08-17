"""UI configuration flow for Solar Shutters."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AZIMUTH_END,
    CONF_AZIMUTH_START,
    CONF_COVER_ENTITY,
    CONF_DAWN_DUSK_AWAY,
    CONF_ENABLED,
    CONF_ONLY_AWAY,
    CONF_PRESENCE_ENTITIES,
    CONF_TELEWORK_ENABLED,
    CONF_TELEWORK_END,
    CONF_TELEWORK_START,
    CONF_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_THRESHOLD,
    CONF_WINDOW_NAME,
    DEFAULT_DAWN_DUSK_AWAY,
    DEFAULT_ENABLED,
    DEFAULT_ONLY_AWAY,
    DEFAULT_TELEWORK_ENABLED,
    DEFAULT_TELEWORK_END,
    DEFAULT_TELEWORK_START,
    DEFAULT_TEMPERATURE_THRESHOLD,
    DOMAIN,
)


def _entity_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the static window setup schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_WINDOW_NAME, default=defaults.get(CONF_WINDOW_NAME, "")
            ): selector.TextSelector(),
            vol.Required(
                CONF_COVER_ENTITY,
                default=defaults.get(CONF_COVER_ENTITY, vol.UNDEFINED),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
            vol.Required(
                CONF_TEMPERATURE_ENTITY,
                default=defaults.get(CONF_TEMPERATURE_ENTITY, vol.UNDEFINED),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class=SensorDeviceClass.TEMPERATURE
                )
            ),
            vol.Required(
                CONF_PRESENCE_ENTITIES,
                default=defaults.get(CONF_PRESENCE_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["person", "device_tracker"], multiple=True
                )
            ),
            vol.Required(
                CONF_AZIMUTH_START,
                default=defaults.get(CONF_AZIMUTH_START, 90.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=360, step=1, unit_of_measurement="°"
                )
            ),
            vol.Required(
                CONF_AZIMUTH_END,
                default=defaults.get(CONF_AZIMUTH_END, 180.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=360, step=1, unit_of_measurement="°"
                )
            ),
        }
    )


def _behavior_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build initial behavior settings used by the control entities."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_TEMPERATURE_THRESHOLD,
                default=defaults.get(
                    CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-10,
                    max=50,
                    step=0.5,
                    unit_of_measurement=UnitOfTemperature.CELSIUS,
                )
            ),
            vol.Required(
                CONF_ENABLED, default=defaults.get(CONF_ENABLED, DEFAULT_ENABLED)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_ONLY_AWAY,
                default=defaults.get(CONF_ONLY_AWAY, DEFAULT_ONLY_AWAY),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_TELEWORK_ENABLED,
                default=defaults.get(CONF_TELEWORK_ENABLED, DEFAULT_TELEWORK_ENABLED),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_TELEWORK_START,
                default=defaults.get(
                    CONF_TELEWORK_START, DEFAULT_TELEWORK_START.isoformat()
                ),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_TELEWORK_END,
                default=defaults.get(
                    CONF_TELEWORK_END, DEFAULT_TELEWORK_END.isoformat()
                ),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_DAWN_DUSK_AWAY,
                default=defaults.get(CONF_DAWN_DUSK_AWAY, DEFAULT_DAWN_DUSK_AWAY),
            ): selector.BooleanSelector(),
        }
    )


class SolarShuttersConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one independently controlled window."""

    VERSION = 1

    def __init__(self) -> None:
        self._window_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect linked entities and solar orientation."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_COVER_ENTITY])
            self._abort_if_unique_id_configured()
            self._window_data = user_input
            return await self.async_step_behavior()
        return self.async_show_form(step_id="user", data_schema=_entity_schema())

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect initial behavior; it remains editable through entities."""
        if user_input is not None:
            data = {**self._window_data, **user_input}
            return self.async_create_entry(title=data[CONF_WINDOW_NAME], data=data)
        return self.async_show_form(step_id="behavior", data_schema=_behavior_schema())

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return SolarShuttersOptionsFlow()


class SolarShuttersOptionsFlow(config_entries.OptionsFlow):
    """Edit all settings after initial setup."""

    def __init__(self) -> None:
        self._window_data: dict[str, Any] = {}

    @property
    def _defaults(self) -> dict[str, Any]:
        return {
            **self.config_entry.data,
            **self.config_entry.options,
            CONF_WINDOW_NAME: self.config_entry.title,
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._window_data = user_input
            return await self.async_step_behavior()
        return self.async_show_form(
            step_id="init", data_schema=_entity_schema(self._defaults)
        )

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            title = self._window_data.pop(CONF_WINDOW_NAME)
            options = {**self.config_entry.options, **self._window_data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, title=title)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="behavior", data_schema=_behavior_schema(self._defaults)
        )
