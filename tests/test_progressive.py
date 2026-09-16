"""Time-driven scenarios for progressive control using real decision code."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def state(value, **attributes):
    return SimpleNamespace(state=value, attributes=attributes)


@pytest.fixture
def rig(integration):
    class Rig:
        def __init__(self):
            self.module = integration.controller
            self.hass = MagicMock()
            self.hass.services.async_call = AsyncMock()
            self.hass.async_create_task.side_effect = asyncio.create_task
            self.states = {
                "sun.sun": state("above_horizon", azimuth=180, elevation=45),
                "cover.window": state(
                    "open", current_position=100, supported_features=4
                ),
                "sensor.indoor": state("24"),
                "sensor.outdoor": state("24"),
                "person.owner": state("not_home"),
            }
            self.hass.states.get.side_effect = self.states.get
            self.entry = SimpleNamespace(
                entry_id="window",
                title="Window",
                options={},
                data={
                    "cover_entity": "cover.window",
                    "temperature_entity": "sensor.indoor",
                    "presence_entities": ["person.owner"],
                    "azimuth_start": 90,
                    "azimuth_end": 270,
                    "progressive_enabled": True,
                    "facade_azimuth": 180,
                    "window_height": 2,
                    "sill_height": 0,
                    "sun_depth": 1,
                },
            )
            self.manager = integration.global_settings.GlobalSettingsManager(self.hass)
            self.controller = self.module.ShutterController(
                self.hass, self.entry, self.manager
            )
            self.base = datetime(2026, 9, 16, 12, tzinfo=UTC)
            self.clock(0)

        def clock(self, minute):
            self.now = self.base + timedelta(minutes=minute)
            self.module.dt_util.utcnow.return_value = self.now
            self.module.dt_util.as_local.return_value = self.now

        async def evaluate(self, minute):
            self.clock(minute)
            await self.controller.async_evaluate("test")

        @property
        def commands(self):
            return [
                call.kwargs["service_data"]["position"]
                for call in self.hass.services.async_call.await_args_list
            ]

        def settle(self):
            cover = self.states["cover.window"]
            old = state(cover.state, **cover.attributes)
            target = self.commands[-1]
            cover.attributes["current_position"] = target
            cover.state = "closed" if target == 0 else "open"
            self.controller._handle_cover_state_change(cover, old)

        async def start(self):
            await self.evaluate(0)
            await self.evaluate(5)
            self.settle()

    return Rig()


def run(coroutine):
    asyncio.run(coroutine)


def test_confirmation_interval_and_no_repeated_commands(rig):
    async def scenario():
        await rig.evaluate(0)
        await rig.evaluate(4)
        assert rig.commands == []
        await rig.evaluate(5)
        assert rig.commands == [50]
        rig.settle()
        assert not rig.controller.manual_override
        rig.states["sensor.indoor"].state = "25"
        await rig.evaluate(6)
        await rig.evaluate(11)
        assert rig.controller.wait_reason == "command_interval"
        await rig.evaluate(34)
        assert rig.commands == [50]
        await rig.evaluate(35)
        assert rig.commands == [50, 20]
        rig.settle()
        await rig.evaluate(70)
        assert rig.commands == [50, 20]

    run(scenario())


def test_small_fluctuations_do_not_move_cover(rig):
    async def scenario():
        await rig.start()
        for minute in range(6, 181):
            rig.states["sensor.indoor"].state = "24.1" if minute % 2 else "23.9"
            await rig.evaluate(minute)
        assert rig.commands == [50]

    run(scenario())


def test_changed_candidate_restarts_confirmation(rig):
    async def scenario():
        await rig.evaluate(0)
        rig.states["sensor.indoor"].state = "25"
        await rig.evaluate(4)
        await rig.evaluate(5)
        assert rig.commands == []
        await rig.evaluate(9)
        assert rig.commands == [20]

    run(scenario())


def test_no_sun_reopens_after_five_minutes_and_ignores_cooldown(rig):
    async def scenario():
        await rig.start()
        rig.states["sun.sun"].attributes["azimuth"] = 280
        await rig.evaluate(6)
        await rig.evaluate(10)
        assert rig.commands == [50]
        await rig.evaluate(11)
        assert rig.commands == [50, 100]
        assert not rig.controller.managed_closed

    run(scenario())


def test_sun_return_resets_no_sun_confirmation(rig):
    async def scenario():
        await rig.start()
        rig.states["sun.sun"].attributes["azimuth"] = 280
        await rig.evaluate(6)
        rig.states["sun.sun"].attributes["azimuth"] = 180
        await rig.evaluate(9)
        rig.states["sun.sun"].attributes["azimuth"] = 280
        await rig.evaluate(10)
        await rig.evaluate(14)
        assert rig.commands == [50]
        await rig.evaluate(15)
        assert rig.commands == [50, 100]

    run(scenario())


@pytest.mark.parametrize(
    "invalid_sun",
    [None, state("unavailable"), state("above_horizon", azimuth="nan", elevation=45)],
)
def test_invalid_sun_holds_position_and_restarts_confirmation(rig, invalid_sun):
    async def scenario():
        await rig.start()
        rig.states["sun.sun"] = invalid_sun
        await rig.evaluate(6)
        await rig.evaluate(40)
        assert rig.commands == [50]
        assert rig.controller.wait_reason == "sun_unavailable"
        rig.states["sun.sun"] = state("above_horizon", azimuth=280, elevation=45)
        await rig.evaluate(41)
        await rig.evaluate(45)
        assert rig.commands == [50]
        await rig.evaluate(46)
        assert rig.commands == [50, 100]

    run(scenario())


@pytest.mark.parametrize("change", ["disabled", "presence", "telework_end"])
def test_authorization_end_releases_immediately(rig, change):
    async def scenario():
        if change == "telework_end":
            rig.states["person.owner"].state = "home"
            rig.manager.settings.update(telework_enabled=True, telework_end="12:06:00")
        await rig.start()
        if change == "disabled":
            rig.manager.settings["enabled"] = False
        elif change == "presence":
            rig.states["person.owner"].state = "home"
        await rig.evaluate(6)
        assert rig.commands == [50, 100]

    run(scenario())


def test_night_priority_and_dawn_release(rig):
    async def scenario():
        await rig.start()
        rig.manager.settings["dawn_dusk_away"] = True
        rig.states["sun.sun"] = state("below_horizon", azimuth=280, elevation=-5)
        await rig.evaluate(6)
        assert rig.commands == [50, 0]
        rig.settle()
        rig.states["person.owner"].state = "home"
        await rig.evaluate(10)
        assert rig.commands == [50, 0]
        rig.states["sun.sun"] = state("above_horizon", azimuth=80, elevation=5)
        await rig.evaluate(11)
        assert rig.commands == [50, 0, 100]

    run(scenario())


def test_missing_indoor_temperature_closes_completely(rig):
    async def scenario():
        rig.states["sensor.indoor"] = state("unavailable")
        await rig.evaluate(0)
        await rig.evaluate(5)
        assert rig.commands == [0]

    run(scenario())


def test_thermal_hysteresis_and_reopening_keep_interval(rig):
    async def scenario():
        await rig.start()
        rig.states["sensor.indoor"].state = "23.6"
        await rig.evaluate(6)
        await rig.evaluate(11)
        assert rig.controller.shading_required
        assert rig.commands == [50]
        rig.states["sensor.indoor"].state = "23.4"
        await rig.evaluate(12)
        await rig.evaluate(17)
        assert not rig.controller.shading_required
        assert rig.controller.wait_reason == "command_interval"
        await rig.evaluate(35)
        assert rig.commands == [50, 100]

    run(scenario())


def test_already_near_target_does_not_claim_manual_shutter(rig):
    async def scenario():
        rig.states["cover.window"].attributes["current_position"] = 52
        await rig.evaluate(0)
        await rig.evaluate(5)
        assert rig.commands == []
        assert not rig.controller.managed_closed
        rig.states["sun.sun"].attributes["azimuth"] = 280
        await rig.evaluate(6)
        await rig.evaluate(11)
        assert rig.commands == []

    run(scenario())


def test_failed_priority_command_is_not_retried_every_minute(rig):
    async def scenario():
        await rig.start()
        rig.manager.settings["enabled"] = False
        rig.hass.services.async_call.side_effect = RuntimeError("offline")
        await rig.evaluate(6)
        for minute in range(7, 36):
            await rig.evaluate(minute)
        assert rig.commands == [50, 100]
        await rig.evaluate(36)
        assert rig.commands == [50, 100, 100]

    run(scenario())


def test_unavailable_shutter_does_not_fall_back_to_binary_commands(rig):
    async def scenario():
        await rig.start()
        rig.states["cover.window"] = state("unavailable")
        await rig.evaluate(10)
        assert rig.controller.wait_reason == "cover_unavailable"
        assert rig.commands == [50]

    run(scenario())


def test_manual_intervention_during_service_does_not_restore_ownership(rig):
    async def scenario():
        await rig.evaluate(0)

        async def service(*args, **kwargs):
            old = rig.states["cover.window"]
            new = state("opening", current_position=100, supported_features=4)
            rig.controller._handle_cover_state_change(new, old)

        rig.hass.services.async_call.side_effect = service
        await rig.evaluate(5)
        assert rig.controller.manual_override
        assert not rig.controller.managed_closed

    run(scenario())


@pytest.mark.parametrize("source", ["sensor.outdoor", "weather.home"])
def test_outdoor_sensor_or_weather_anticipates_heat(rig, source):
    async def scenario():
        rig.manager.settings["outdoor_temperature_entity"] = source
        rig.states[source] = (
            state("sunny", temperature=30, temperature_unit="°C")
            if source.startswith("weather.")
            else state("30", unit_of_measurement="°C")
        )
        await rig.evaluate(0)
        await rig.evaluate(5)
        assert rig.controller.effective_threshold == 23
        assert rig.commands == [20]

    run(scenario())


def test_missing_outdoor_temperature_disables_only_anticipation(rig):
    async def scenario():
        rig.manager.settings["outdoor_temperature_entity"] = "sensor.missing"
        await rig.start()
        assert rig.commands == [50]
        assert rig.controller.effective_threshold == 24

    run(scenario())


def test_failed_command_waits_thirty_minutes_before_retry(rig):
    async def scenario():
        rig.hass.services.async_call.side_effect = RuntimeError("offline")
        await rig.evaluate(0)
        await rig.evaluate(5)
        assert not rig.controller.managed_closed
        assert rig.controller.wait_reason == "command_failed"
        for minute in range(6, 35):
            await rig.evaluate(minute)
        assert rig.commands == [50]
        rig.hass.services.async_call.side_effect = None
        await rig.evaluate(35)
        assert rig.commands == [50, 50]

    run(scenario())


def test_parallel_evaluations_send_only_one_command(rig):
    async def scenario():
        await rig.evaluate(0)
        rig.clock(5)

        async def service(*args, **kwargs):
            await asyncio.sleep(0)

        rig.hass.services.async_call.side_effect = service
        await asyncio.gather(
            *(rig.controller.async_evaluate("event") for _ in range(5))
        )
        assert rig.commands == [50]

    run(scenario())


def test_moving_or_unknown_position_never_gets_a_command(rig):
    async def scenario():
        cover = rig.states["cover.window"]
        cover.state = "closing"
        await rig.evaluate(0)
        await rig.evaluate(5)
        assert rig.controller.wait_reason == "moving"
        cover.state = "open"
        cover.attributes.pop("current_position")
        await rig.evaluate(6)
        assert rig.controller.wait_reason == "position_unavailable"
        assert rig.commands == []

    run(scenario())


def test_manual_position_change_is_respected_until_cycle_ends(rig):
    async def scenario():
        await rig.start()
        old = rig.states["cover.window"]
        new = state("open", current_position=70, supported_features=4)
        rig.states["cover.window"] = new
        rig.controller._handle_cover_state_change(new, old)
        await rig.evaluate(40)
        assert rig.controller.manual_override
        assert rig.commands == [50]
        rig.states["sun.sun"].attributes["azimuth"] = 280
        await rig.evaluate(41)
        await rig.evaluate(46)
        assert not rig.controller.manual_override
        assert rig.commands == [50]  # Do not reopen a manually positioned shutter.
        rig.states["sun.sun"].attributes["azimuth"] = 180
        await rig.evaluate(50)
        await rig.evaluate(55)
        assert rig.commands == [50, 50]

    run(scenario())


@pytest.mark.parametrize("reversal", [False, True])
def test_expected_progress_and_manual_reversal(rig, reversal):
    async def scenario():
        await rig.evaluate(0)
        await rig.evaluate(5)
        old = rig.states["cover.window"]
        moving = state("closing", current_position=80, supported_features=4)
        rig.controller._handle_cover_state_change(moving, old)
        assert not rig.controller.manual_override
        if reversal:
            new = state("opening", current_position=85, supported_features=4)
            rig.controller._handle_cover_state_change(new, moving)
            assert rig.controller.manual_override
        else:
            rig.states["cover.window"] = moving
            rig.settle()
            assert not rig.controller.manual_override

    run(scenario())


def test_unchanged_position_attributes_are_not_manual(rig):
    async def scenario():
        await rig.start()
        rig.clock(10)
        old = rig.states["cover.window"]
        new = state(
            "open", current_position=50, supported_features=4, friendly_name="New"
        )
        rig.controller._handle_cover_state_change(new, old)
        assert not rig.controller.manual_override

    run(scenario())


def test_final_position_reports_within_tolerance_are_not_manual(rig):
    async def scenario():
        await rig.evaluate(0)
        await rig.evaluate(5)
        previous = rig.states["cover.window"]
        for position in (80, 60, 52, 51, 50):
            current = state("open", current_position=position, supported_features=4)
            rig.controller._handle_cover_state_change(current, previous)
            assert not rig.controller.manual_override
            previous = current

    run(scenario())


def test_restart_restores_ownership_interval_and_reconfirms_target(rig):
    async def scenario():
        await rig.start()
        saved = rig.controller._store.async_save.call_args.args[0]
        replacement = rig.module.ShutterController(rig.hass, rig.entry, rig.manager)
        replacement._store.async_load.return_value = saved
        rig.controller = replacement
        rig.states["sensor.indoor"].state = "25"
        rig.clock(7)
        await replacement.async_setup()
        assert replacement.managed_closed
        assert replacement.last_position_target == 50
        await rig.evaluate(12)
        assert replacement.wait_reason == "command_interval"
        await rig.evaluate(35)
        assert rig.commands == [50, 20]

    run(scenario())


def test_legacy_state_is_restored_without_new_fields(rig):
    async def scenario():
        rig.controller._store.async_load.return_value = {
            "managed_closed": True,
            "last_desired_closed": True,
        }
        await rig.controller.async_setup()
        assert rig.controller.managed_closed
        assert rig.controller.last_position_target is None
        assert rig.commands == []

    run(scenario())


@pytest.mark.parametrize("change", ["disabled", "unsupported", "missing_geometry"])
def test_binary_fallback(rig, change):
    async def scenario():
        if change == "disabled":
            rig.entry.data["progressive_enabled"] = False
        elif change == "unsupported":
            rig.states["cover.window"].attributes["supported_features"] = 0
        else:
            rig.entry.data.pop("window_height")
        await rig.evaluate(0)
        assert rig.hass.services.async_call.await_args.args == ("cover", "close_cover")

    run(scenario())


@pytest.mark.parametrize("weather", [False, True])
def test_temperature_conversion_uses_source_units(integration, weather):
    converter = integration.controller.TemperatureConverter.convert
    converter.return_value = 30
    reading = (
        state("sunny", temperature=86, temperature_unit="°F")
        if weather
        else state("86", unit_of_measurement="°F")
    )
    assert (
        integration.controller.ShutterController._temperature_in_celsius(
            reading, weather=weather
        )
        == 30
    )
    converter.assert_called_once_with(86, "°F", "°C")
