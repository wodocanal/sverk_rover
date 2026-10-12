import json
import math
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rover_web.named_places import (
    GRID_MAJOR_CELLS, NamedPlacesMixin, NamedPlacesStore, grid_cell_corners,
    grid_cell_at_point, grid_major_center, inspection_corners, inspection_grid_route,
    major_grid_detour, vlm_obstacle_label,
)


def point(name='Диван', **changes):
    return {'name': name, 'x': 1.0, 'y': 2.0, 'yaw': 0.5, **changes}


def field_grid():
    return {'corners': [
        {'x': 0.0, 'y': 1.0}, {'x': 1.0, 'y': 1.0},
        {'x': 1.0, 'y': 0.0}, {'x': 0.0, 'y': 0.0},
    ]}


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
    calibrated = store.update('map', 0, grid=field_grid())
    assert calibrated['grid']['rows'] == 10
    assert calibrated['grid']['columns'] == 10
    zone = {'name': 'Завал', 'can_drive': False, 'aliases': ['обломки'],
            'cells': [{'row': 2, 'column': 3}, {'row': 2, 'column': 4}]}
    saved = store.update('map', 1, zone=zone)
    assert saved['zones'][0]['name'] == 'Завал'
    assert not saved['zones'][0]['can_drive']
    assert saved['zones'][0]['cells'] == zone['cells']
    with pytest.raises(ValueError, match='inside'):
        store.update('map', 2, zone={**zone, 'name': 'Плохая', 'cells': [{'row': 10, 'column': 0}]})
    with pytest.raises(ValueError, match='changing'):
        store.update('map', 2, grid={'corners': [
            {'x': 0.1, 'y': 1.0}, {'x': 1.0, 'y': 1.0},
            {'x': 1.0, 'y': 0.0}, {'x': 0.0, 'y': 0.0},
        ]})
    assert store.update('map', 2, delete_zone_id=saved['zones'][0]['id'])['zones'] == []


def test_grid_cells_are_bilinear_and_inspection_requires_rectangle(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    saved = store.update('map', 0, grid=field_grid())
    corners = grid_cell_corners(saved['grid'], 0, 0)
    assert corners[0]['x'] == pytest.approx(0.0)
    assert corners[0]['y'] == pytest.approx(1.0)
    assert corners[2]['x'] == pytest.approx(0.1)
    assert corners[2]['y'] == pytest.approx(0.9)
    rectangle = {'cells': [{'row': 1, 'column': 1}, {'row': 1, 'column': 2}]}
    inspection = inspection_corners(rectangle, saved['grid'])
    assert inspection[2]['x'] == pytest.approx(0.3)
    assert inspection[2]['y'] == pytest.approx(0.8)
    with pytest.raises(ValueError, match='solid rectangular'):
        inspection_corners({'cells': [{'row': 1, 'column': 1}, {'row': 2, 'column': 2}]}, saved['grid'])


def test_grid_cell_at_point_reports_small_and_large_cell_coordinates():
    cell = grid_cell_at_point(field_grid(), 0.26, 0.74)

    assert cell['row'] == 2
    assert cell['column'] == 2
    assert cell['row_number'] == 3
    assert cell['column_number'] == 3
    assert cell['major_row'] == 1
    assert cell['major_column'] == 1
    assert cell['center'] == pytest.approx({'x': 0.25, 'y': 0.75})


@pytest.mark.parametrize(('obstacle_class', 'label'), [
    ('traffic_accident', 'ДТП'),
    ('fuel_truck', 'бензовоз'),
    ('fallen_tree', 'упавшее дерево'),
    ('building_debris', 'обломки здания'),
    ('any', 'любое препятствие'),
])
def test_vlm_obstacle_labels_are_operator_friendly(obstacle_class, label):
    assert vlm_obstacle_label(obstacle_class) == label


def test_zone_inspection_route_uses_neighbour_large_cell_centers_and_nearest_start(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    grid = store.update('map', 0, grid=field_grid())['grid']
    zone = {'cells': [
        {'row': 2, 'column': 4}, {'row': 2, 'column': 5},
        {'row': 3, 'column': 4}, {'row': 3, 'column': 5},
    ]}
    route = inspection_grid_route(zone, grid, {'x': 0.69, 'y': 0.89})
    expected_cells = {
        (0, 1), (0, 2), (0, 3), (1, 1),
        (1, 3), (2, 1), (2, 2), (2, 3),
    }
    assert len(route) == len(expected_cells)
    assert {(item['major_row'], item['major_column']) for item in route} == expected_cells
    assert (route[0]['major_row'], route[0]['major_column']) == (0, 3)
    assert route[0]['x'] == pytest.approx(0.7)
    assert route[0]['y'] == pytest.approx(0.9)
    assert route[0]['yaw'] == pytest.approx(-math.pi / 2)
    area = sum(route[index]['x'] * route[(index + 1) % len(route)]['y']
               - route[(index + 1) % len(route)]['x'] * route[index]['y']
               for index in range(len(route)))
    assert area < 0  # Clockwise in the map coordinate frame.


def test_zone_inspection_route_can_run_counterclockwise(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    grid = store.update('map', 0, grid=field_grid())['grid']
    zone = {'cells': [
        {'row': 2, 'column': 4}, {'row': 2, 'column': 5},
        {'row': 3, 'column': 4}, {'row': 3, 'column': 5},
    ]}
    route = inspection_grid_route(
        zone, grid, {'x': 0.69, 'y': 0.89}, 'counterclockwise',
    )
    area = sum(route[index]['x'] * route[(index + 1) % len(route)]['y']
               - route[(index + 1) % len(route)]['x'] * route[index]['y']
               for index in range(len(route)))
    assert area > 0


def test_zone_inspection_rejects_edge_without_a_complete_neighbour_ring(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    grid = store.update('map', 0, grid=field_grid())['grid']
    with pytest.raises(ValueError, match='one free large grid cell'):
        inspection_grid_route({'cells': [{'row': 0, 'column': 4}]}, grid, {'x': 0.5, 'y': 0.5})


def test_major_grid_detour_avoids_confirmed_obstacle_cell():
    grid = {'corners': [
        {'x': 0.0, 'y': 0.0}, {'x': 5.0, 'y': 0.0},
        {'x': 5.0, 'y': 5.0}, {'x': 0.0, 'y': 5.0},
    ]}
    route = major_grid_detour(
        grid,
        grid_major_center(grid, 2, 1),
        grid_major_center(grid, 2, 3),
        {(2, 2)},
    )

    assert (route[0]['major_row'], route[0]['major_column']) == (2, 1)
    assert (route[-1]['major_row'], route[-1]['major_column']) == (2, 3)
    assert (2, 2) not in {(point['major_row'], point['major_column']) for point in route}
    assert all(0 <= point['major_row'] < GRID_MAJOR_CELLS for point in route)


def test_vlm_classification_reads_nested_observation_event_type():
    response = json.dumps({
        'timestamp': 1790605965.4068267,
        'latency_sec': 14.96,
        'observation': {'event_type': 'traffic_accident', 'confidence': 0.9},
    })

    assert NamedPlacesMixin._vlm_classification(response) == 'traffic_accident'
    assert NamedPlacesMixin._vlm_classification('{"observation": {"event_type": "none"}}') == 'none'


def test_vlm_classification_accepts_all_supported_event_types():
    for event_type in ('traffic_accident', 'fuel_truck', 'fallen_tree', 'building_debris'):
        assert NamedPlacesMixin._vlm_classification(
            json.dumps({'observation': {'event_type': event_type}})
        ) == event_type


def test_target_qr_candidates_reach_other_sides_without_entering_obstacle_cell():
    grid = {'corners': [
        {'x': 0.0, 'y': 0.0}, {'x': 5.0, 'y': 0.0},
        {'x': 5.0, 'y': 5.0}, {'x': 0.0, 'y': 5.0},
    ]}
    obstacle = {**grid_major_center(grid, 2, 2), 'class': 'traffic_accident'}
    current_side = grid_major_center(grid, 2, 1)

    candidates = NamedPlacesMixin._target_qr_candidates(
        None, grid, {(2, 2)}, current_side, obstacle
    )

    cells = {(item['major_row'], item['major_column']) for item in candidates}
    assert cells == {(1, 2), (2, 3), (3, 2)}
    for candidate in candidates:
        expected_yaw = math.atan2(
            obstacle['y'] - candidate['y'], obstacle['x'] - candidate['x']
        )
        assert candidate['yaw'] == pytest.approx(expected_yaw)


def test_zone_requires_grid_cells(tmp_path):
    store = NamedPlacesStore(tmp_path / 'places.json')
    with pytest.raises(ValueError, match='Stretch'):
        store.update('map', 0, zone={'name': 'Bad', 'can_drive': False, 'aliases': [],
                                     'cells': [{'row': 0, 'column': 0}]})


def test_no_drive_zone_creates_navigation_map_copy(gateway):
    payload = gateway.named_places_payload('map.yaml')
    gateway.update_named_places({'action': 'save_grid', 'map': 'map.yaml',
                                 'map_id': payload['map_id'], 'revision': payload['revision'],
                                 'grid': {'corners': [
                                     {'x': 0, 'y': 0.1}, {'x': 0.1, 'y': 0.1},
                                     {'x': 0.1, 'y': 0}, {'x': 0, 'y': 0},
                                 ]}})
    payload = gateway.named_places_payload('map.yaml')
    gateway.update_named_places({'action': 'save_zone', 'map': 'map.yaml',
                                 'map_id': payload['map_id'], 'revision': payload['revision'],
                                 'zone': {'name': 'Завал', 'can_drive': False, 'aliases': [],
                                          'cells': [{'row': 0, 'column': 0}]}})
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
