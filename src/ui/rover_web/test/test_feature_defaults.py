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
