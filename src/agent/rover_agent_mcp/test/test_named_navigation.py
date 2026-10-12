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
    assert set(tools) == {'list_search_areas', 'search_static_obstacle'}
    search = tools['search_static_obstacle']['inputSchema']['properties']
    assert search['wait_at_qr_sec']['default'] == 5
    assert 'building_debris' in search['target_obstacle']['enum']


def test_search_waits_for_qr_and_uses_inspection_return(monkeypatch):
    node = agent()
    node._named_places_call = Mock(side_effect=[
        {'success': True, 'inspection': {'state': 'starting'}},
        {'success': True, 'inspection': {'state': 'waiting_to_return'}},
        {'success': True, 'inspection': {
            'state': 'returned', 'completion_state': 'succeeded',
            'qr_codes': ['victim-17'],
        }},
    ])
    sleep = Mock()
    monkeypatch.setattr('rover_agent_mcp.named_navigation.time.sleep', sleep)

    result = node.search_static_obstacle('желтый дом', 'building_debris')

    assert result['success']
    assert result['qr_codes'] == ['victim-17']
    assert result['return_to_start']['completed']
    assert node._named_places_call.call_args_list[0].args == ('start_inspection', {
        'name': 'желтый дом', 'target_obstacle': 'building_debris', 'return_wait_sec': 5.0,
    })
