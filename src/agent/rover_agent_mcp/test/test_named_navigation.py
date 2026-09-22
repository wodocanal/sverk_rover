from unittest.mock import Mock

import pytest

from rover_agent_mcp.named_navigation import NamedNavigationMixin
from rover_agent_mcp.tool_schemas import mcp_tools


def agent():
    node = NamedNavigationMixin()
    node._nav_status = {'active': False}
    node._named_navigation_token = None
    return node


@pytest.mark.parametrize('state,success', [('succeeded', True), ('aborted', False), ('canceled', False), ('error', False)])
def test_waits_for_real_result(state, success):
    node = agent()
    node._named_places_call = Mock(side_effect=[
        {'success': True, 'token': {'instance': 'a', 'generation': 1}, 'name': 'Диван'},
        {'success': True, 'navigation': {'running': True, 'goal_state': state}},
    ])
    result = node.navigate_to_named_place('Диван')
    assert result['success'] is success
    assert result['completed'] is success


def test_nonblocking_is_not_arrival():
    node = agent()
    node._named_places_call = Mock(return_value={'success': True, 'token': {'generation': 1}})
    result = node.navigate_to_named_place('Кухня', wait_until_done=False)
    assert result['success'] and not result['completed']
    assert node._named_places_call.call_count == 1


def test_timeout_cancels_only_owned_goal(monkeypatch):
    node = agent()
    token = {'instance': 'a', 'generation': 1}
    node._named_places_call = Mock(return_value={'success': True, 'token': token})
    monkeypatch.setattr('rover_agent_mcp.named_navigation.time.monotonic', Mock(side_effect=[0, 2]))
    result = node.navigate_to_named_place('Диван', timeout_s=1)
    assert not result['success'] and not result['completed']
    node._named_places_call.assert_called_with('cancel', {'token': token})


def test_lost_service_does_not_report_arrival():
    node = agent()
    node._named_places_call = Mock(side_effect=[
        {'success': True, 'token': {'generation': 1}}, {'success': False, 'error': 'lost'},
        {'success': False, 'error': 'lost'},
    ])
    result = node.navigate_to_named_place('Диван')
    assert not result['success'] and not result['cancel_result']['success']


def test_schema_has_named_tools():
    tools = {t['name']: t for t in mcp_tools()}
    assert 'list_named_places' in tools
    assert tools['navigate_to_named_place']['inputSchema']['properties']['wait_until_done']['default']
    steps = tools['run_motion_sequence']['inputSchema']['properties']['steps']['items']['properties']
    assert 'navigate_to_named_place' in steps['type']['enum']
    assert 'name' in steps
