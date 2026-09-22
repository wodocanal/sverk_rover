from pathlib import Path

import pytest

from rover_base_driver.drive_types import (
    DIFFERENTIAL,
    MECANUM,
    normalize_drive_type,
    read_drive_type,
    write_drive_type,
)
from rover_base_driver.kinematics import (
    inverse_differential,
    inverse_kinematics,
)


def test_differential_kinematics_uses_left_and_right_wheel_pairs():
    assert inverse_differential(0.4, 1.0, 0.2) == pytest.approx(
        (0.3, 0.5, 0.3, 0.5)
    )


def test_differential_dispatch_ignores_lateral_velocity():
    wheels = inverse_kinematics(DIFFERENTIAL, 0.25, 99.0, -0.5, 0.14, 0.2)
    assert wheels == pytest.approx((0.3, 0.2, 0.3, 0.2))


def test_mecanum_dispatch_preserves_lateral_velocity():
    wheels = inverse_kinematics(MECANUM, 0.25, 0.1, 0.0, 0.14, 0.2)
    assert wheels == pytest.approx((0.15, 0.35, 0.35, 0.15))


def test_drive_type_file_round_trip(tmp_path: Path):
    path = tmp_path / 'nested' / 'drive_type'
    assert read_drive_type(path, MECANUM) == MECANUM
    assert write_drive_type(path, DIFFERENTIAL) == path
    assert read_drive_type(path, MECANUM) == DIFFERENTIAL
    with pytest.raises(ValueError):
        normalize_drive_type('tracks')
