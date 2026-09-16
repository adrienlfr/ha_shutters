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
    CONF_FACADE_AZIMUTH,
    CONF_ONLY_AWAY,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITIES,
    CONF_PROGRESSIVE_ENABLED,
    CONF_SILL_HEIGHT,
    CONF_SUN_DEPTH,
    CONF_TELEWORK_ENABLED,
    CONF_TELEWORK_END,
    CONF_TELEWORK_START,
    CONF_TEMPERATURE_ENTITY,
    CONF_TEMPERATURE_THRESHOLD,
    CONF_WINDOW_HEIGHT,
    CONF_WINDOW_NAME,
    DATA_GLOBAL_MANAGER,
    DEFAULT_DAWN_DUSK_AWAY,
    DEFAULT_ENABLED,
    DEFAULT_ONLY_AWAY,
    DEFAULT_TELEWORK_ENABLED,
    DEFAULT_TELEWORK_END,
    DEFAULT_TELEWORK_START,
    DEFAULT_TEMPERATURE_THRESHOLD,
    DOMAIN,
    GEOMETRY_KEYS,
    GLOBAL_SETTING_KEYS,
)
from .global_settings import GlobalSettingsManager
from .logic import finite_float


def _outdoor_schema(defaults: dict[str, Any]) -> dict:
    """Offer a shared, optional sensor or current weather temperature."""
    return {
        vol.Optional(
            CONF_OUTDOOR_TEMPERATURE_ENTITY,
            description={
                "suggested_value": defaults.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, "")
            },
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                filter=[
                    {"domain": "sensor", "device_class": "temperature"},
                    {"domain": "weather"},
                ]
            )
        )
    }


def _geometry_errors(values: dict[str, Any]) -> dict[str, str]:
    if not values.get(CONF_PROGRESSIVE_ENABLED, False):
        return {}
    errors = {}
    for key in GEOMETRY_KEYS:
        value = finite_float(values.get(key))
        if value is None:
            errors[key] = "geometry_required"
        elif (
            (key == CONF_FACADE_AZIMUTH and not 0 <= value <= 360)
            or (key in (CONF_WINDOW_HEIGHT, CONF_SUN_DEPTH) and value <= 0)
            or (key == CONF_SILL_HEIGHT and value < 0)
        ):
            errors[key] = "invalid_geometry"
    return errors


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
            vol.Required(
                CONF_PROGRESSIVE_ENABLED,
                default=defaults.get(CONF_PROGRESSIVE_ENABLED, False),
            ): selector.BooleanSelector(),
            **{
                vol.Optional(
                    key, default=defaults.get(key, vol.UNDEFINED)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=minimum,
                        **({"max": 360} if key == CONF_FACADE_AZIMUTH else {}),
                        step=1 if key == CONF_FACADE_AZIMUTH else 0.01,
                        unit_of_measurement="°" if key == CONF_FACADE_AZIMUTH else "m",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
                for key, minimum in (
                    (CONF_FACADE_AZIMUTH, 0),
                    (CONF_WINDOW_HEIGHT, 0.01),
                    (CONF_SILL_HEIGHT, 0),
                    (CONF_SUN_DEPTH, 0.01),
                )
            },
        }
    )


def _behavior_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build initial behavior settings used by the control entities."""
    defaults = defaults or {}
    return vol.Schema(
        {
            **_outdoor_schema(defaults),
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
        errors = _geometry_errors(user_input) if user_input is not None else {}
        if errors:
            return self.async_show_form(
                step_id="user", data_schema=_entity_schema(user_input), errors=errors
            )
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_COVER_ENTITY])
            self._abort_if_unique_id_configured()
            self._window_data = user_input
            if self.hass.config_entries.async_entries(DOMAIN):
                return self.async_create_entry(
                    title=user_input[CONF_WINDOW_NAME], data=user_input
                )
            return await self.async_step_behavior()
        return self.async_show_form(step_id="user", data_schema=_entity_schema())

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect shared behavior when the first window is created."""
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
    """Edit the window geometry and the shared outdoor source."""

    @property
    def _defaults(self) -> dict[str, Any]:
        return {
            **self.config_entry.data,
            **self.config_entry.options,
            CONF_OUTDOOR_TEMPERATURE_ENTITY: self.hass.data[DOMAIN][
                DATA_GLOBAL_MANAGER
            ].settings.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, ""),
            CONF_WINDOW_NAME: self.config_entry.title,
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        if DATA_GLOBAL_MANAGER not in domain_data:
            manager = GlobalSettingsManager(self.hass)
            await manager.async_initialize(self.config_entry)
            domain_data[DATA_GLOBAL_MANAGER] = manager
        errors = _geometry_errors(user_input) if user_input is not None else {}
        if errors:
            return self.async_show_form(
                step_id="init",
                data_schema=_entity_schema(user_input).extend(
                    _outdoor_schema(user_input)
                ),
                errors=errors,
            )
        if user_input is not None:
            user_input = dict(user_input)
            title = user_input.pop(CONF_WINDOW_NAME)
            outdoor = user_input.pop(CONF_OUTDOOR_TEMPERATURE_ENTITY, "")
            await self.hass.data[DOMAIN][DATA_GLOBAL_MANAGER].async_update(
                CONF_OUTDOOR_TEMPERATURE_ENTITY, outdoor
            )
            options = {
                key: value
                for key, value in self.config_entry.options.items()
                if key not in GLOBAL_SETTING_KEYS
            }
            options.update(user_input)
            self.hass.config_entries.async_update_entry(self.config_entry, title=title)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="init",
            data_schema=_entity_schema(self._defaults).extend(
                _outdoor_schema(self._defaults)
            ),
        )
