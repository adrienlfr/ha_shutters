"""Tests for pure Solar Shutters decisions."""

import importlib.util
from datetime import time
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "indoor,outdoor,expected",
    [
        (24, None, 24),
        (None, 30, 24),
        (24, 20, 24),
        (24, 26, 24),
        (24, 28, 23.5),
        (24, 30, 23),
        (24, 40, 23),
    ],
)
def test_outdoor_anticipation(indoor, outdoor, expected):
    assert logic.effective_temperature_threshold(24, indoor, outdoor) == expected


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, 50),
        ({"indoor": 25}, 25),
        ({"indoor": 26}, 0),
        ({"indoor": None}, 0),
        ({"sill": 0.8}, 10),
        ({"sill": 1.2}, 0),
        ({"elevation": 10}, 8.816349),
        ({"elevation": 80}, 100),
        ({"elevation": 0}, 100),
        ({"azimuth": 240}, 100),
        ({"azimuth": 269.999999}, 100),
        ({"azimuth": 270}, 100),
        ({"azimuth": 0}, 100),
        ({"facade": 350, "azimuth": 350}, 50),
    ],
)
def test_geometric_opening(changes, expected):
    arguments = dict(
        azimuth=180,
        elevation=45,
        facade=180,
        height=2,
        sill=0,
        depth=1,
        indoor=24,
        threshold=24,
    )
    arguments.update(changes)
    assert logic.geometric_opening(**arguments) == pytest.approx(expected, abs=1e-5)


@pytest.mark.parametrize(
    "opening,previous,expected",
    [
        (57, None, 50),
        (49.99999999999999, None, 50),
        (51, 50, 50),
        (45, 50, 50),
        (65, 50, 50),
        (44, 50, 40),
        (66, 50, 60),
        (0, 10, 0),
        (100, None, 100),
    ],
)
def test_position_steps_and_dead_band(opening, previous, expected):
    assert logic.opening_step(opening, previous) == expected


@pytest.mark.parametrize("value", [None, "unknown", "nan", "inf", "-inf", "bad"])
def test_invalid_measurements(value):
    assert logic.finite_float(value) is None
