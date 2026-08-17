"""Pure decision helpers for Solar Shutters."""

from __future__ import annotations

from datetime import time


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
