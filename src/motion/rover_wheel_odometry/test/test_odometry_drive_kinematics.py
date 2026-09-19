import pytest

from rover_wheel_odometry.kinematics import (
    forward_differential,
    forward_kinematics,
)


def test_differential_odometry_averages_each_side():
    dx, dy, dyaw = forward_differential((0.28, 0.52, 0.32, 0.48), 0.2)
    assert (dx, dy, dyaw) == pytest.approx((0.4, 0.0, 1.0))


def test_differential_odometry_never_reports_lateral_motion():
    dx, dy, dyaw = forward_kinematics(
        'differential',
        (0.2, 0.4, 0.2, 0.4),
        0.14,
        0.2,
    )
    assert (dx, dy, dyaw) == pytest.approx((0.3, 0.0, 1.0))
