"""Tests for pure Solar Shutters decisions."""

import importlib.util
from datetime import time
from pathlib import Path

LOGIC_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ha_shutters" / "logic.py"
)
SPEC = importlib.util.spec_from_file_location("ha_shutters_logic", LOGIC_PATH)
assert SPEC and SPEC.loader
logic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(logic)


def test_azimuth_regular_range() -> None:
    assert logic.azimuth_is_in_range(135, 90, 180)
    assert logic.azimuth_is_in_range(90, 90, 180)
    assert not logic.azimuth_is_in_range(270, 90, 180)


def test_azimuth_range_crossing_north() -> None:
    assert logic.azimuth_is_in_range(350, 300, 40)
    assert logic.azimuth_is_in_range(20, 300, 40)
    assert not logic.azimuth_is_in_range(180, 300, 40)


def test_daytime_schedule() -> None:
    assert logic.time_is_in_range(time(10), time(8), time(18))
    assert not logic.time_is_in_range(time(19), time(8), time(18))
    assert not logic.time_is_in_range(time(18), time(8), time(18))


def test_overnight_schedule() -> None:
    assert logic.time_is_in_range(time(23), time(22), time(6))
    assert logic.time_is_in_range(time(5), time(22), time(6))
    assert not logic.time_is_in_range(time(12), time(22), time(6))


def test_away_only_can_be_overridden_by_telework_schedule() -> None:
    assert logic.automation_is_allowed(
        enabled=True,
        only_away=True,
        someone_home=False,
        telework_enabled=False,
        telework_active=False,
    )
    assert logic.automation_is_allowed(
        enabled=True,
        only_away=True,
        someone_home=True,
        telework_enabled=True,
        telework_active=True,
    )
    assert not logic.automation_is_allowed(
        enabled=True,
        only_away=True,
        someone_home=True,
        telework_enabled=True,
        telework_active=False,
    )


def test_master_switch_always_wins() -> None:
    assert not logic.automation_is_allowed(
        enabled=False,
        only_away=False,
        someone_home=False,
        telework_enabled=True,
        telework_active=True,
    )
