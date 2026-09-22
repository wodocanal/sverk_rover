from __future__ import annotations

from typing import Sequence

from rover_base_driver.drive_types import (
    DIFFERENTIAL,
    MECANUM,
    normalize_drive_type,
)


def forward_mecanum(wheels: Sequence[float], wheelbase: float, track: float):
    fl, fr, rl, rr = (float(v) for v in wheels)
    k = (wheelbase + track) / 2.0
    return (
        (fl + fr + rl + rr) / 4.0,
        (-fl + fr + rl - rr) / 4.0,
        (-fl + fr - rl + rr) / (4.0 * k),
    )


def forward_differential(wheels: Sequence[float], track: float):
    fl, fr, rl, rr = (float(v) for v in wheels)
    left = (fl + rl) / 2.0
    right = (fr + rr) / 2.0
    return (
        (left + right) / 2.0,
        0.0,
        (right - left) / track,
    )


def forward_kinematics(
    drive_type: str,
    wheels: Sequence[float],
    wheelbase: float,
    track: float,
):
    normalized = normalize_drive_type(drive_type)
    if normalized == MECANUM:
        return forward_mecanum(wheels, wheelbase, track)
    if normalized == DIFFERENTIAL:
        return forward_differential(wheels, track)
    raise AssertionError(f'Unhandled drive type: {normalized}')
