"""Regression coverage for shading with missing temperature readings."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.parametrize(
    "reading, expected",
    [
        (None, True),
        ("unavailable", True),
        ("unknown", True),
        ("invalid", True),
        ("nan", True),
        ("inf", True),
        ("23", False),
        ("24", True),
        ("25", True),
    ],
)
def test_temperature_controls_shading(integration, reading, expected):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    states = {
        "sun.sun": SimpleNamespace(
            state="above_horizon", attributes={"azimuth": 135, "elevation": 45}
        ),
        "cover.window": SimpleNamespace(state="open"),
        "sensor.temperature": (
            None if reading is None else SimpleNamespace(state=reading, attributes={})
        ),
    }
    hass.states.get.side_effect = states.get
    entry = SimpleNamespace(
        entry_id="window",
        title="Window",
        data={
            "cover_entity": "cover.window",
            "temperature_entity": "sensor.temperature",
            "azimuth_start": 90,
            "azimuth_end": 180,
        },
        options={},
    )
    manager = integration.global_settings.GlobalSettingsManager(hass)
    manager.settings["only_away"] = False
    controller = integration.controller.ShutterController(hass, entry, manager)
    now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    integration.controller.dt_util.utcnow.return_value = now
    integration.controller.dt_util.as_local.return_value = now

    asyncio.run(controller.async_evaluate("test"))

    assert controller.shading_required is expected
    assert controller.managed_closed is expected
    assert hass.services.async_call.await_count == int(expected)
    if expected:
        assert hass.services.async_call.call_args.args == ("cover", "close_cover")

    # A working sensor returning a cool reading releases an owned shutter.
    states["sensor.temperature"] = SimpleNamespace(state="22", attributes={})
    states["cover.window"].state = "closed"
    asyncio.run(controller.async_evaluate("sensor_recovered"))
    assert not controller.shading_required
    assert not controller.managed_closed
    if expected:
        assert hass.services.async_call.call_args.args == ("cover", "open_cover")
