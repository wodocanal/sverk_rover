from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rover_web.web_gateway_node import RoverWebGateway


@pytest.mark.parametrize('mode,visible,expected', [
    ('auto', True, True), ('auto', False, False),
    ('enabled', False, True), ('disabled', True, False),
])
def test_visibility_defaults(mode, visible, expected):
    node = SimpleNamespace(
        get_parameter=lambda _: SimpleNamespace(value=mode),
        _node_is_visible=Mock(return_value=visible),
    )
    assert RoverWebGateway._page_enabled(node, 'voice_page_mode', '/voice') is expected
    assert node._node_is_visible.call_count == (1 if mode == 'auto' else 0)


def test_invalid_visibility_mode():
    node = SimpleNamespace(get_parameter=lambda _: SimpleNamespace(value='invalid'))
    with pytest.raises(ValueError):
        RoverWebGateway._page_enabled(node, 'voice_page_mode', '/voice')


def test_differential_drive_rejects_lateral_command():
    node = SimpleNamespace(
        max_linear_speed=0.35,
        max_lateral_speed=0.35,
        max_angular_speed=1.5,
        drive_type='differential',
        _lock=Lock(),
        _latest_drive_command=None,
        _latest_drive_monotonic=0.0,
        _motor_calibration_active=False,
    )
    result = RoverWebGateway.set_drive_command(node, 0.2, 0.3, 0.7)
    assert result['command'] == {
        'linear_x': pytest.approx(0.2),
        'linear_y': 0.0,
        'angular_z': pytest.approx(0.7),
    }
