import json
import math
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rover_web.named_places import NamedPlacesMixin, NamedPlacesStore


def point(name='Диван', **changes):
    return {'name': name, 'x': 1.0, 'y': 2.0, 'yaw': 0.5, **changes}


def test_store_persistence_rename_conflict_delete(tmp_path):
    path = tmp_path / 'config' / 'places.json'
    store = NamedPlacesStore(path)
    first = store.update('map-a', 0, point=point())
    saved = first['places'][0]
    assert NamedPlacesStore(path).get('map-a') == first
    assert store.get('map-b')['places'] == []
    with pytest.raises(ValueError, match='another window'):
        store.update('map-a', 0, point=point('Кухня'))
    with pytest.raises(ValueError, match='already exists'):
        store.update('map-a', 1, point=point('диван'))
    renamed = store.update('map-a', 1, point={**saved, 'name': 'Кухня'})
    assert renamed['places'][0]['name'] == 'Кухня'
    assert store.update('map-a', 2, delete_id=saved['id'])['places'] == []
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('change', [{'x': math.nan}, {'y': math.inf}, {'name': ''}, {'name': 'x\nq'}, {'name': 'x' * 81}])
def test_invalid_points_do_not_write(tmp_path, change):
    store = NamedPlacesStore(tmp_path / 'places.json')
    with pytest.raises(ValueError):
        store.update('map', 0, point=point(**change))
    assert not store.path.exists()


def test_corrupt_file_is_not_silently_overwritten(tmp_path):
    path = tmp_path / 'places.json'
    path.write_text('{bad')
    with pytest.raises(json.JSONDecodeError):
        NamedPlacesStore(path).update('map', 0, point=point())
    assert path.read_text() == '{bad'


def test_zone_persistence_and_validation(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    zone = {'name': 'Завал', 'can_drive': False, 'aliases': ['обломки'], 'corners': [
        {'x': 0, 'y': 0}, {'x': 1, 'y': 0}, {'x': 1, 'y': 1}, {'x': 0, 'y': 1},
    ]}
    saved = store.update('map', 0, zone=zone)
    assert saved['zones'][0]['name'] == 'Завал'
    assert not saved['zones'][0]['can_drive']
    with pytest.raises(ValueError, match='exactly four'):
        store.update('map', 1, zone={**zone, 'name': 'Плохая', 'corners': zone['corners'][:3]})
    assert store.update('map', 1, delete_zone_id=saved['zones'][0]['id'])['zones'] == []


def test_zone_inspection_route_is_clockwise_parallel_and_spaced():
    route = NamedPlacesMixin._zone_inspection_route([
        {'x': 0, 'y': 0}, {'x': 2, 'y': 0}, {'x': 2, 'y': 1}, {'x': 0, 'y': 1},
    ], clearance_m=0.3, step_m=0.25)
    # The 30 cm offset expands the 2x1 m rectangle to 2.6x1.6 m.
    assert len(route) == 36
    assert min(point['x'] for point in route) == pytest.approx(-0.3)
    assert max(point['x'] for point in route) == pytest.approx(2.3)
    assert min(point['y'] for point in route) == pytest.approx(-0.3)
    assert max(point['y'] for point in route) == pytest.approx(1.3)
    area = sum(route[index]['x'] * route[(index + 1) % len(route)]['y']
               - route[(index + 1) % len(route)]['x'] * route[index]['y']
               for index in range(len(route)))
    assert area < 0  # Clockwise in the map coordinate frame.


def test_non_convex_zone_is_rejected(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    with pytest.raises(ValueError, match='convex'):
        store.update('map', 0, zone={'name': 'Bad', 'can_drive': False, 'aliases': [], 'corners': [
            {'x': 0, 'y': 0}, {'x': 1, 'y': 0}, {'x': 0.4, 'y': 0.2}, {'x': 0, 'y': 1},
        ]})


def test_no_drive_zone_creates_navigation_map_copy(gateway):
    payload = gateway.named_places_payload('map.yaml')
    gateway.update_named_places({'action': 'save_zone', 'map': 'map.yaml',
                                 'map_id': payload['map_id'], 'revision': payload['revision'],
                                 'zone': {'name': 'Завал', 'can_drive': False, 'aliases': [], 'corners': [
                                     {'x': 0, 'y': 0}, {'x': 0.1, 'y': 0},
                                     {'x': 0.1, 'y': 0.1}, {'x': 0, 'y': 0.1},
                                 ]}})
    generated = gateway.navigation_map_with_zones('map.yaml')
    assert generated != gateway._resolve_map_yaml.return_value
    assert generated.exists()
    assert generated.with_suffix('.pgm').exists()


@pytest.fixture
def gateway(tmp_path):
    node = NamedPlacesMixin()
    node._lock = threading.RLock()
    node._navigation_control_lock = threading.RLock()
    node._navigation_generation = 0
    node._places_prepared = None
    node._places_instance = 'test'
    node._places_map_cache = {}
    node._places_runtime_map_id = None
    node._places_store = NamedPlacesStore(tmp_path / 'places.json')
    node._motor_calibration_active = False
    node._odom = object()
    node._topic_state = {'odom': SimpleNamespace(received_monotonic=time.monotonic())}
    node._pose_payload = Mock(return_value={'x': 0, 'y': 0, 'yaw': 0, 'frame_id': 'odom'})
    node._navigation_pose = Mock(side_effect=lambda pose, _: pose)
    node._assert_navigation_runtime_idle = Mock()
    node.navigation_status_payload = Mock(return_value={
        'running': False, 'mode': None, 'phase': 'idle', 'map': '', 'goal_state': 'idle'})
    node.start_navigation = Mock(return_value={'running': True, 'goal_state': 'queued'})
    node.send_navigation_goal = Mock(return_value={'running': True, 'goal_state': 'queued'})
    node.cancel_navigation_goal = Mock(return_value={'goal_state': 'canceling'})
    image = tmp_path / 'map.pgm'
    image.write_bytes(b'P2\n2 2\n255\n0 255 255 0\n')
    metadata = tmp_path / 'map.yaml'
    metadata.write_text('image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n')
    node._resolve_map_yaml = Mock(return_value=metadata)
    node._resolve_map_image = Mock(return_value=image)
    node.maps_payload = Mock(return_value={'maps': [{'path': 'map.yaml'}]})
    map_id = node._places_map_id('map.yaml')
    node._places_store.update(map_id, 0, point=point())
    return node


def prepare(node):
    return node.update_named_places({'action': 'prepare', 'map': 'map.yaml',
                                    'initial_pose': {'x': 0, 'y': 0, 'yaw': 0}})


def test_agent_can_list_but_cannot_move_without_preparation(gateway):
    data = gateway.named_places_command('list', {})
    assert data['maps'][0]['places'][0]['name'] == 'Диван'
    assert data['active_map'] == ''
    with pytest.raises(RuntimeError, match='confirm'):
        gateway.named_places_command('navigate', {'name': 'Диван'})
    gateway.start_navigation.assert_not_called()


def test_prepared_navigation_and_unknown_or_wrong_map(gateway):
    prepare(gateway)
    with pytest.raises(ValueError, match='another map'):
        gateway.named_places_command('navigate', {'name': 'Диван', 'map': 'other.yaml'})
    with pytest.raises(ValueError, match='No point'):
        gateway.named_places_command('navigate', {'name': 'unknown'})
    result = gateway.named_places_command('navigate', {'name': 'диван'})
    assert result['name'] == 'Диван'
    assert result['token'] == {'instance': 'test', 'generation': 0}
    gateway.start_navigation.assert_called_once_with({
        'map': 'map.yaml', 'initial_pose': {'x': 0, 'y': 0, 'yaw': 0},
        'goal': {'x': 1, 'y': 2, 'yaw': 0.5}})
    assert gateway._places_prepared is None


@pytest.mark.parametrize('reason', ['expired', 'moved', 'rotated', 'moving', 'stale', 'generation', 'map'])
def test_invalidated_preparation_never_moves(gateway, reason):
    prepare(gateway)
    if reason == 'expired': gateway._places_prepared['expires'] = 0
    if reason == 'moved': gateway._pose_payload.return_value['x'] = 1  # replace to avoid shared mock dict
    if reason == 'rotated': gateway._pose_payload.return_value['yaw'] = 0.5
    if reason == 'moving': gateway._pose_payload.return_value['vx'] = 0.12
    if reason in {'moved', 'rotated'}:
        gateway._places_prepared['odom'] = {'x': 0, 'y': 0, 'yaw': 0, 'frame_id': 'odom'}
    if reason == 'stale': gateway._topic_state['odom'].received_monotonic = 0
    if reason == 'generation': gateway._navigation_generation += 1
    if reason == 'map': gateway._resolve_map_image.return_value.write_bytes(b'new scan')
    with pytest.raises(RuntimeError):
        gateway.named_places_command('navigate', {'name': 'Диван'})
    gateway.start_navigation.assert_not_called()


def test_running_navigation_uses_same_stack_and_checks_map(gateway):
    gateway.navigation_status_payload.return_value.update(
        running=True, mode='navigation', phase='running', map='map.yaml', map_pose={'x': 0, 'y': 0})
    gateway._places_runtime_map_id = gateway._places_map_id('map.yaml')
    gateway.named_places_command('navigate', {'name': 'Диван'})
    gateway.send_navigation_goal.assert_called_once()
    gateway.start_navigation.assert_not_called()
    gateway._resolve_map_image.return_value.write_bytes(b'new scan')
    with pytest.raises(RuntimeError, match='Map on disk changed'):
        gateway.named_places_command('navigate', {'name': 'Диван'})


def test_goal_token_prevents_stale_success_or_cancel(gateway):
    token = {'instance': 'test', 'generation': 0}
    assert gateway.named_places_command('status', {'token': token})['navigation']['goal_state'] == 'idle'
    gateway._navigation_generation += 1
    for action in ['status', 'cancel']:
        with pytest.raises(RuntimeError, match='no longer current'):
            gateway.named_places_command(action, {'token': token})
    gateway.cancel_navigation_goal.assert_not_called()


def test_map_revision_guard(gateway):
    payload = gateway.named_places_payload('map.yaml')
    gateway._resolve_map_image.return_value.write_bytes(b'new scan')
    assert gateway.named_places_payload('map.yaml')['places'] == []
    with pytest.raises(ValueError, match='Map changed'):
        gateway.update_named_places({'action': 'save', 'map': 'map.yaml',
                                    'map_id': payload['map_id'], 'revision': 1, 'point': point()})
