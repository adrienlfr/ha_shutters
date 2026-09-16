"""Load integration modules with mocked Home Assistant service boundaries."""

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def integration(monkeypatch):
    """Exercise the real controllers without installing Home Assistant."""
    package_name = "ha_shutters_under_test"
    package = ModuleType(package_name)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "ha_shutters")
    ]
    monkeypatch.setitem(sys.modules, package_name, package)
    modules = {
        "homeassistant.components.cover": {
            "DOMAIN": "cover",
            "SERVICE_CLOSE_COVER": "close_cover",
            "SERVICE_OPEN_COVER": "open_cover",
            "SERVICE_SET_COVER_POSITION": "set_cover_position",
            "CoverEntityFeature": SimpleNamespace(SET_POSITION=4),
        },
        "homeassistant.config_entries": {"ConfigEntry": MagicMock()},
        "homeassistant.const": {
            "ATTR_UNIT_OF_MEASUREMENT": "unit_of_measurement",
            **{
                f"STATE_{state.upper()}": state
                for state in (
                    "closed",
                    "closing",
                    "home",
                    "open",
                    "opening",
                    "unavailable",
                    "unknown",
                )
            },
            "UnitOfTemperature": SimpleNamespace(CELSIUS="°C"),
        },
        "homeassistant.core": {
            "Event": MagicMock(),
            "HomeAssistant": MagicMock(),
            "State": MagicMock(),
            "callback": lambda function: function,
        },
        "homeassistant.helpers.event": {
            name: MagicMock()
            for name in (
                "async_track_state_change_event",
                "async_track_time_interval",
                "async_track_time_change",
            )
        },
        "homeassistant.helpers.storage": {
            "Store": MagicMock(
                side_effect=lambda *args: SimpleNamespace(
                    async_load=AsyncMock(return_value=None),
                    async_save=AsyncMock(),
                    async_remove=AsyncMock(),
                )
            ),
        },
        "homeassistant.util": {"dt": MagicMock()},
        "homeassistant.util.unit_conversion": {
            "TemperatureConverter": MagicMock(),
        },
    }
    for name, attributes in modules.items():
        parts = name.split(".")
        for length in range(1, len(parts) + 1):
            module_name = ".".join(parts[:length])
            if module_name not in sys.modules:
                module = ModuleType(module_name)
                module.__path__ = []
                monkeypatch.setitem(sys.modules, module_name, module)
        module = sys.modules[name]
        for key, value in attributes.items():
            monkeypatch.setattr(module, key, value, raising=False)
    loaded = {}
    for name in ("const", "logic", "global_settings", "controller"):
        full_name = f"{package_name}.{name}"
        # Register with monkeypatch before importing so teardown removes it.
        monkeypatch.setitem(sys.modules, full_name, None)
        del sys.modules[full_name]
        loaded[name] = importlib.import_module(full_name)
    return SimpleNamespace(**loaded)
