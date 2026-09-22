from types import SimpleNamespace

import pytest

from rover_web.web_gateway_node import RoverWebGateway


def test_navigation_pose_accepts_finite_coordinates():
    pose = RoverWebGateway._navigation_pose(
        {'x': '1.25', 'y': -0.5, 'yaw': 0},
        'goal',
    )
    assert pose == {'x': 1.25, 'y': -0.5, 'yaw': 0.0}


@pytest.mark.parametrize('value', [None, {}, {'x': 0, 'y': 0, 'yaw': float('nan')}])
def test_navigation_pose_rejects_incomplete_or_nonfinite_values(value):
    with pytest.raises(ValueError):
        RoverWebGateway._navigation_pose(value, 'goal')


def test_navigation_prerequisites_report_missing_topics():
    node = SimpleNamespace(
        navigation_scan_topic='/scan_filtered',
        odom_topic='/odom',
        count_publishers=lambda name: 1,
        get_topic_names_and_types=lambda: [
            ('/odom', ['nav_msgs/msg/Odometry']),
            ('/tf', ['tf2_msgs/msg/TFMessage']),
        ],
    )
    result = RoverWebGateway._navigation_prerequisites(node)
    assert result['ready'] is False
    assert result['missing_topics'] == ['/scan_filtered', '/tf_static']


def test_navigation_prerequisites_require_publishers_not_just_subscribers():
    required = ['/scan_filtered', '/odom', '/tf', '/tf_static']
    node = SimpleNamespace(
        navigation_scan_topic='/scan_filtered',
        odom_topic='/odom',
        get_topic_names_and_types=lambda: [(name, []) for name in required],
        count_publishers=lambda name: 0 if name == '/odom' else 1,
    )
    result = RoverWebGateway._navigation_prerequisites(node)
    assert result['ready'] is False
    assert result['missing_topics'] == ['/odom']
