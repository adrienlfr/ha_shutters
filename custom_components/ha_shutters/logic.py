"""Pure decision helpers for Solar Shutters."""

from __future__ import annotations

from datetime import time
from math import cos, floor, isfinite, radians, tan


def finite_float(value: object) -> float | None:
    """Read a measurement, excluding NaN and infinities."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def effective_temperature_threshold(
    threshold: float, indoor: float | None, outdoor: float | None
) -> float:
    """Anticipate outdoor heat by lowering the indoor threshold by at most 1°C."""
    if indoor is None or outdoor is None:
        return threshold
    return threshold - max(0.0, min(1.0, (outdoor - indoor - 2.0) / 4.0))


def sun_is_in_front(azimuth: float, facade: float) -> bool:
    """Exclude the back of the facade and exactly grazing incidence."""
    return abs((azimuth - facade + 180) % 360 - 180) < 90


def geometric_opening(
    *,
    azimuth: float,
    elevation: float,
    facade: float,
    height: float,
    sill: float,
    depth: float,
    indoor: float | None,
    threshold: float,
) -> float:
    """Limit floor-level sun penetration through a top-down shutter."""
    if elevation <= 0 or not sun_is_in_front(azimuth, facade):
        return 100.0
    if indoor is None or indoor >= threshold + 2:
        return 0.0
    reinforcement = max(0.0, min(1.0, (indoor - threshold) / 2.0))
    allowed_depth = depth * (1.0 - reinforcement)
    incidence = max(1e-6, cos(radians(azimuth - facade)))
    opening = allowed_depth * tan(radians(min(elevation, 89.999999))) / incidence
    return max(0.0, min(100.0, 100.0 * (opening - sill) / height))


def opening_step(opening: float, previous: int | None) -> int:
    """Quantize to 10-point steps with a dead band around the commanded step."""
    if previous is not None and previous - 5 <= opening <= previous + 15:
        return previous
    return max(0, min(100, int(floor((opening + 1e-9) / 10)) * 10))


def azimuth_is_in_range(azimuth: float, start: float, end: float) -> bool:
    """Return whether an azimuth is in a range, including north wrap-around."""
    azimuth = azimuth % 360
    start = start % 360
    end = end % 360
    if start <= end:
        return start <= azimuth <= end
    return azimuth >= start or azimuth <= end


def time_is_in_range(now: time, start: time, end: time) -> bool:
    """Return whether a time is in a daily range, including overnight ranges."""
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def automation_is_allowed(
    *,
    enabled: bool,
    only_away: bool,
    someone_home: bool,
    telework_enabled: bool,
    telework_active: bool,
) -> bool:
    """Return whether solar shading automation may currently run."""
    if not enabled:
        return False
    if not only_away:
        return True
    return not someone_home or (telework_enabled and telework_active)
