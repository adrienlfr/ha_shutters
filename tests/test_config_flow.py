"""Exercise geometry validation and shared-source updates with real schemas."""

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def flow(integration, monkeypatch):
    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        async def async_set_unique_id(self, unique_id):
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            pass

    class Selector:
        def __init__(self, config=None):
            self.config = config

        def __call__(self, value):
            return value

    entries = sys.modules["homeassistant.config_entries"]
    monkeypatch.setattr(entries, "ConfigFlow", Flow, raising=False)
    monkeypatch.setattr(entries, "OptionsFlow", Flow, raising=False)
    monkeypatch.setattr(
        sys.modules["homeassistant"], "config_entries", entries, raising=False
    )
    sensor = ModuleType("homeassistant.components.sensor")
    sensor.SensorDeviceClass = SimpleNamespace(TEMPERATURE="temperature")
    monkeypatch.setitem(sys.modules, sensor.__name__, sensor)
    selectors = SimpleNamespace(
        EntitySelector=Selector,
        NumberSelector=Selector,
        BooleanSelector=Selector,
        TextSelector=Selector,
        TimeSelector=Selector,
        EntitySelectorConfig=dict,
        NumberSelectorConfig=dict,
        NumberSelectorMode=SimpleNamespace(BOX="box"),
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"], "selector", selectors, raising=False
    )
    name = "ha_shutters_under_test.config_flow"
    monkeypatch.setitem(sys.modules, name, None)
    del sys.modules[name]
    return importlib.import_module(name)


@pytest.fixture
def window():
    return {
        "window_name": "Window",
        "cover_entity": "cover.window",
        "temperature_entity": "sensor.indoor",
        "presence_entities": [],
        "azimuth_start": 90,
        "azimuth_end": 270,
        "progressive_enabled": True,
        "facade_azimuth": 180,
        "window_height": 2,
        "sill_height": 0,
        "sun_depth": 1,
    }


@pytest.mark.parametrize(
    "key", ["facade_azimuth", "window_height", "sill_height", "sun_depth"]
)
def test_progressive_requires_each_measurement(flow, window, key):
    window.pop(key)
    instance = flow.SolarShuttersConfigFlow()
    result = asyncio.run(instance.async_step_user(window))
    assert result["type"] == "form"
    assert result["errors"] == {key: "geometry_required"}


@pytest.mark.parametrize(
    "key,value",
    [
        ("window_height", 0),
        ("sun_depth", -1),
        ("sill_height", -1),
        ("facade_azimuth", 361),
        ("sun_depth", float("nan")),
    ],
)
def test_invalid_geometry_is_rejected(flow, window, key, value):
    window[key] = value
    assert key in flow._geometry_errors(window)


def test_existing_window_defaults_to_binary_without_invented_geometry(flow, window):
    for key in (
        "progressive_enabled",
        "facade_azimuth",
        "window_height",
        "sill_height",
        "sun_depth",
    ):
        window.pop(key)
    validated = flow._entity_schema()(window)
    assert validated["progressive_enabled"] is False
    assert "window_height" not in validated
    assert flow._geometry_errors(validated) == {}


def test_first_window_collects_outdoor_source_in_shared_behavior(flow, window):
    instance = flow.SolarShuttersConfigFlow()
    instance.hass = MagicMock()
    instance.hass.config_entries.async_entries.return_value = []
    result = asyncio.run(instance.async_step_user(window))
    assert result["step_id"] == "behavior"
    values = result["data_schema"]({"outdoor_temperature_entity": "weather.home"})
    created = asyncio.run(instance.async_step_behavior(values))
    assert created["data"]["outdoor_temperature_entity"] == "weather.home"
    assert created["data"]["window_height"] == 2


def test_options_can_open_when_no_window_is_loaded(flow, window):
    instance = flow.SolarShuttersOptionsFlow()
    instance.hass = MagicMock()
    instance.hass.data = {}
    instance.config_entry = SimpleNamespace(data=window, options={}, title="Window")
    result = asyncio.run(instance.async_step_init())
    assert result["type"] == "form"
    assert "global_settings_manager" in instance.hass.data["ha_shutters"]


@pytest.mark.parametrize("source", ["weather.home", "sensor.outdoor", None])
def test_options_update_shared_outdoor_source_and_keep_geometry(
    flow, integration, window, source
):
    instance = flow.SolarShuttersOptionsFlow()
    instance.hass = MagicMock()
    manager = integration.global_settings.GlobalSettingsManager(instance.hass)
    manager.settings["outdoor_temperature_entity"] = "sensor.previous"
    instance.hass.data = {"ha_shutters": {"global_settings_manager": manager}}
    instance.config_entry = SimpleNamespace(
        data=window.copy(), options={}, title="Window"
    )
    form = asyncio.run(instance.async_step_init())
    submitted = window.copy()
    if source is not None:
        submitted["outdoor_temperature_entity"] = source
    validated = form["data_schema"](submitted)
    if source is None:
        assert "outdoor_temperature_entity" not in validated
    result = asyncio.run(instance.async_step_init(validated))
    assert result["type"] == "create_entry"
    assert result["data"]["window_height"] == 2
    assert "outdoor_temperature_entity" not in result["data"]
    assert manager.settings["outdoor_temperature_entity"] == (source or "")
    manager._store.async_save.assert_awaited_once()
