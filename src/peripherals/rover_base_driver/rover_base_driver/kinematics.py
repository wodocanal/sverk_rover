from __future__ import annotations

from typing import Iterable

from .drive_types import DIFFERENTIAL, MECANUM, normalize_drive_type

WheelTuple = tuple[float, float, float, float]


def inverse_mecanum(
    vx: float, vy: float, wz: float, wheelbase: float, track_width: float
) -> WheelTuple:
    k = (wheelbase + track_width) / 2.0
    return (
        vx - vy - k * wz,
        vx + vy + k * wz,
        vx + vy - k * wz,
        vx - vy + k * wz,
    )


def inverse_differential(
    vx: float, wz: float, track_width: float
) -> WheelTuple:
    half_track = track_width / 2.0
    left = vx - half_track * wz
    right = vx + half_track * wz
    return left, right, left, right


def inverse_kinematics(
    drive_type: str,
    vx: float,
    vy: float,
    wz: float,
    wheelbase: float,
    track_width: float,
) -> WheelTuple:
    normalized = normalize_drive_type(drive_type)
    if normalized == MECANUM:
        return inverse_mecanum(vx, vy, wz, wheelbase, track_width)
    if normalized == DIFFERENTIAL:
        return inverse_differential(vx, wz, track_width)
    raise AssertionError(f'Unhandled drive type: {normalized}')


def scale_wheels(values: Iterable[float], limit: float) -> WheelTuple:
    wheels = tuple(float(value) for value in values)
    if len(wheels) != 4:
        raise ValueError('Four wheel values are required')
    peak = max(abs(value) for value in wheels)
    if peak <= limit:
        return wheels  # type: ignore[return-value]
    factor = limit / peak
    return tuple(value * factor for value in wheels)  # type: ignore[return-value]
