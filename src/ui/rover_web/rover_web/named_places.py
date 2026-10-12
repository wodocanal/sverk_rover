"""Persistent, map-bound destinations shared by the web UI and MCP agent."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import unicodedata
import uuid
from collections import deque

import yaml
import cv2
import numpy as np


def place_name(value):
    if not isinstance(value, str):
        raise ValueError('Point name must be text')
    name = unicodedata.normalize('NFC', value).strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
            raise ValueError('Point name must contain 1-80 printable characters')
    return name


def zone_corners(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('A zone must have exactly four corners')
    corners = []
    for point in value:
        if not isinstance(point, dict):
            raise ValueError('Zone corner must be an object')
        corner = {key: float(point[key]) for key in ('x', 'y')}
        if not all(math.isfinite(item) for item in corner.values()):
            raise ValueError('Zone corners must be finite')
        corners.append(corner)
    area = sum(corners[index]['x'] * corners[(index + 1) % 4]['y']
               - corners[(index + 1) % 4]['x'] * corners[index]['y'] for index in range(4)) / 2
    if abs(area) < 0.0025:
        raise ValueError('Zone area is too small')
    # A parallel perimeter can be generated safely only around a convex zone.
    turns = []
    for index in range(4):
        first, second, third = (corners[index], corners[(index + 1) % 4],
                                corners[(index + 2) % 4])
        turns.append((second['x'] - first['x']) * (third['y'] - second['y'])
                     - (second['y'] - first['y']) * (third['x'] - second['x']))
    if any(abs(turn) < 1e-8 for turn in turns) or not (
            all(turn > 0 for turn in turns) or all(turn < 0 for turn in turns)):
        raise ValueError('Zone must be a convex quadrilateral')
    for first in range(4):
        ax, ay = corners[first]['x'], corners[first]['y']
        bx, by = corners[(first + 1) % 4]['x'], corners[(first + 1) % 4]['y']
        for second in range(first + 1, 4):
            if second in {first, (first + 1) % 4, (first - 1) % 4}:
                continue
            cx, cy = corners[second]['x'], corners[second]['y']
            dx, dy = corners[(second + 1) % 4]['x'], corners[(second + 1) % 4]['y']
            def cross(px, py, qx, qy, rx, ry):
                return (qx - px) * (ry - py) - (qy - py) * (rx - px)
            if (cross(ax, ay, bx, by, cx, cy) * cross(ax, ay, bx, by, dx, dy) < 0
                    and cross(cx, cy, dx, dy, ax, ay) * cross(cx, cy, dx, dy, bx, by) < 0):
                raise ValueError('Zone sides must not cross')
    return corners


GRID_MAJOR_CELLS = 5
GRID_SUBCELLS = 2
GRID_ROWS = GRID_MAJOR_CELLS * GRID_SUBCELLS
GRID_COLUMNS = GRID_ROWS
VLM_OBSTACLE_CLASSES = (
    'traffic_accident', 'fuel_truck', 'fallen_tree', 'building_debris',
)
VLM_OBSTACLE_LABELS_RU = {
    'traffic_accident': 'ДТП',
    'fuel_truck': 'бензовоз',
    'fallen_tree': 'упавшее дерево',
    'building_debris': 'обломки здания',
    'any': 'любое препятствие',
}
ZONE_INSPECTION_AUTOMATIC_TERMINAL_STATES = {
    'succeeded', 'completed', 'blocked', 'error',
}


def vlm_obstacle_label(obstacle_class):
    """Return the operator-facing label without losing the stable VLM class."""
    normalized = str(obstacle_class or '').strip()
    return VLM_OBSTACLE_LABELS_RU.get(normalized, normalized or 'не указан')


def grid_major_center(grid, row, column):
    center = grid_point(
        grid,
        (row + 0.5) / GRID_MAJOR_CELLS,
        (column + 0.5) / GRID_MAJOR_CELLS,
    )
    return {'x': center['x'], 'y': center['y'], 'major_row': row, 'major_column': column}


def set_route_yaws(route):
    for index, point in enumerate(route):
        following = route[(index + 1) % len(route)] if len(route) > 1 else point
        point['yaw'] = math.atan2(following['y'] - point['y'], following['x'] - point['x'])
    return route


def major_grid_detour(grid, start, goal, forbidden):
    """Find a four-neighbour route through free 5x5 field cells."""
    start_cell = (int(start['major_row']), int(start['major_column']))
    goal_cell = (int(goal['major_row']), int(goal['major_column']))
    blocked = set(forbidden) - {start_cell, goal_cell}
    frontier = deque([start_cell])
    previous = {start_cell: None}
    while frontier:
        row, column = frontier.popleft()
        if (row, column) == goal_cell:
            break
        for candidate in ((row - 1, column), (row, column + 1),
                          (row + 1, column), (row, column - 1)):
            if (candidate in previous or candidate in blocked
                    or not 0 <= candidate[0] < GRID_MAJOR_CELLS
                    or not 0 <= candidate[1] < GRID_MAJOR_CELLS):
                continue
            previous[candidate] = (row, column)
            frontier.append(candidate)
    if goal_cell not in previous:
        raise ValueError('No free grid route remains around the confirmed obstacle')
    cells = []
    current = goal_cell
    while current is not None:
        cells.append(current)
        current = previous[current]
    cells.reverse()
    return [grid_major_center(grid, row, column) for row, column in cells]


def field_grid(value):
    """Validate the four map-frame corners of the fixed competition field."""
    if not isinstance(value, dict):
        raise ValueError('Grid must be an object')
    corners = zone_corners(value.get('corners'))
    return {
        'major_rows': GRID_MAJOR_CELLS,
        'major_columns': GRID_MAJOR_CELLS,
        'subcells_per_major': GRID_SUBCELLS,
        'rows': GRID_ROWS,
        'columns': GRID_COLUMNS,
        'corners': corners,
    }


def grid_cells(value):
    if not isinstance(value, list) or not value:
        raise ValueError('A zone must contain at least one grid cell')
    cells = []
    seen = set()
    for cell in value:
        if not isinstance(cell, dict):
            raise ValueError('Grid cell must be an object')
        row, column = cell.get('row'), cell.get('column')
        if isinstance(row, bool) or isinstance(column, bool):
            raise ValueError('Grid cell indexes must be integers')
        if not isinstance(row, int) or not isinstance(column, int):
            raise ValueError('Grid cell indexes must be integers')
        if not 0 <= row < GRID_ROWS or not 0 <= column < GRID_COLUMNS:
            raise ValueError(f'Grid cell must be inside the {GRID_ROWS}x{GRID_COLUMNS} field')
        if (row, column) in seen:
            raise ValueError('A grid cell may be selected only once')
        seen.add((row, column))
        cells.append({'row': row, 'column': column})
    return sorted(cells, key=lambda item: (item['row'], item['column']))


def grid_point(grid, row_fraction, column_fraction):
    """Bilinear interpolation keeps a stretched grid aligned to a trapezoid field."""
    corners = grid['corners']
    top_left, top_right, bottom_right, bottom_left = corners
    u, v = float(column_fraction), float(row_fraction)
    weights = ((top_left, (1 - u) * (1 - v)), (top_right, u * (1 - v)),
               (bottom_right, u * v), (bottom_left, (1 - u) * v))
    return {
        'x': sum(point['x'] * weight for point, weight in weights),
        'y': sum(point['y'] * weight for point, weight in weights),
    }


def grid_cell_corners(grid, row, column):
    return [
        grid_point(grid, row / GRID_ROWS, column / GRID_COLUMNS),
        grid_point(grid, row / GRID_ROWS, (column + 1) / GRID_COLUMNS),
        grid_point(grid, (row + 1) / GRID_ROWS, (column + 1) / GRID_COLUMNS),
        grid_point(grid, (row + 1) / GRID_ROWS, column / GRID_COLUMNS),
    ]


def grid_cell_at_point(grid, x, y):
    """Return the closest calibrated subcell for a position in the map frame."""
    cells = []
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            center = grid_point(
                grid, (row + 0.5) / GRID_ROWS, (column + 0.5) / GRID_COLUMNS
            )
            cells.append(((center['x'] - x) ** 2 + (center['y'] - y) ** 2,
                          row, column, center))
    _, row, column, center = min(cells)
    return {
        'row': row, 'column': column,
        'row_number': row + 1, 'column_number': column + 1,
        'major_row': row // GRID_SUBCELLS,
        'major_column': column // GRID_SUBCELLS,
        'major_row_number': row // GRID_SUBCELLS + 1,
        'major_column_number': column // GRID_SUBCELLS + 1,
        'center': center,
        'corners': grid_cell_corners(grid, row, column),
    }


def zone_geometry(zone, grid):
    """Return cell polygons; legacy quadrilateral zones remain readable."""
    if zone.get('cells') is not None:
        if not grid:
            raise ValueError('This zone needs a calibrated field grid')
        return [grid_cell_corners(grid, item['row'], item['column'])
                for item in zone['cells']]
    return [zone_corners(zone.get('corners'))]


def inspection_corners(zone, grid):
    """A perimeter route is safe only for a filled rectangular selection."""
    if zone.get('cells') is None:
        return zone_corners(zone.get('corners'))
    if not grid:
        raise ValueError('This zone needs a calibrated field grid')
    cells = {(item['row'], item['column']) for item in zone['cells']}
    rows = [item[0] for item in cells]
    columns = [item[1] for item in cells]
    min_row, max_row = min(rows), max(rows)
    min_column, max_column = min(columns), max(columns)
    expected = {
        (row, column)
        for row in range(min_row, max_row + 1)
        for column in range(min_column, max_column + 1)
    }
    if cells != expected:
        raise ValueError(
            'Inspection requires a solid rectangular group of grid cells'
        )
    return [
        grid_point(grid, min_row / GRID_ROWS, min_column / GRID_COLUMNS),
        grid_point(grid, min_row / GRID_ROWS, (max_column + 1) / GRID_COLUMNS),
        grid_point(grid, (max_row + 1) / GRID_ROWS, (max_column + 1) / GRID_COLUMNS),
        grid_point(grid, (max_row + 1) / GRID_ROWS, min_column / GRID_COLUMNS),
    ]


def inspection_grid_route(zone, grid, current_pose, direction='clockwise'):
    """Build a directional route through centers of cells adjacent to a grid zone."""
    if zone.get('cells') is None:
        raise ValueError('Inspection is available only for zones created from the field grid')
    if not grid:
        raise ValueError('This zone needs a calibrated field grid')

    cells = {(item['row'], item['column']) for item in zone['cells']}
    rows = [item[0] for item in cells]
    columns = [item[1] for item in cells]
    min_row, max_row = min(rows), max(rows)
    min_column, max_column = min(columns), max(columns)
    expected = {
        (row, column)
        for row in range(min_row, max_row + 1)
        for column in range(min_column, max_column + 1)
    }
    if cells != expected:
        raise ValueError('Inspection requires a solid rectangular group of grid cells')
    # The zone is drawn in small cells, but driving happens through centers of
    # the 5x5 field cells. Any selected small cell occupies its parent cell.
    major_cells = {(row // GRID_SUBCELLS, column // GRID_SUBCELLS) for row, column in cells}
    major_rows = [item[0] for item in major_cells]
    major_columns = [item[1] for item in major_cells]
    min_row, max_row = min(major_rows), max(major_rows)
    min_column, max_column = min(major_columns), max(major_columns)
    if (min_row == 0 or min_column == 0
            or max_row == GRID_MAJOR_CELLS - 1 or max_column == GRID_MAJOR_CELLS - 1):
        raise ValueError('The zone needs one free large grid cell on every side for a full inspection route')

    if direction not in {'clockwise', 'counterclockwise'}:
        raise ValueError('Inspection direction must be clockwise or counterclockwise')

    # The ring is ordered clockwise and contains every one-cell-wide neighbour
    # exactly once. The rover therefore remains centered in a free large cell.
    ring = []
    ring.extend((min_row - 1, column) for column in range(min_column - 1, max_column + 2))
    ring.extend((row, max_column + 1) for row in range(min_row, max_row + 2))
    ring.extend((max_row + 1, column) for column in range(max_column, min_column - 2, -1))
    ring.extend((row, min_column - 1) for row in range(max_row, min_row - 1, -1))
    if direction == 'counterclockwise':
        ring.reverse()

    route = []
    for row, column in ring:
        center = grid_point(
            grid,
            (row + 0.5) / GRID_MAJOR_CELLS,
            (column + 0.5) / GRID_MAJOR_CELLS,
        )
        route.append({
            'x': center['x'], 'y': center['y'],
            'major_row': row, 'major_column': column,
        })
    start = min(
        range(len(route)),
        key=lambda index: ((route[index]['x'] - current_pose['x']) ** 2
                           + (route[index]['y'] - current_pose['y']) ** 2, index),
    )
    route = route[start:] + route[:start]
    for index, point in enumerate(route):
        following = route[(index + 1) % len(route)]
        # Every stop faces the next neighbour cell, so QR scanning happens in
        # the direction the rover will continue rather than toward the zone.
        point['yaw'] = math.atan2(following['y'] - point['y'], following['x'] - point['x'])
    return route


class NamedPlacesStore:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {'version': 1, 'maps': {}}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('version') != 1 or not isinstance(data.get('maps'), dict):
            raise ValueError('Invalid named places file; restore it from backup')
        return data

    def get(self, map_id):
        with self.lock:
            entry = self._read()['maps'].get(
                map_id, {'revision': 0, 'places': [], 'zones': [], 'grid': None}
            )
            # The JSON round-trip prevents UI code from mutating the store's
            # in-memory nested lists between a read and a revision-checked write.
            return json.loads(json.dumps({
                **entry, 'places': entry.get('places', []),
                'zones': entry.get('zones', []), 'grid': entry.get('grid'),
            }, ensure_ascii=False))

    def update(self, map_id, revision, *, point=None, delete_id=None, zone=None,
               delete_zone_id=None, grid=None, clear_grid=False):
        with self.lock:
            data = self._read()
            entry = data['maps'].setdefault(
                map_id, {'revision': 0, 'places': [], 'zones': [], 'grid': None}
            )
            entry.setdefault('places', [])
            entry.setdefault('zones', [])
            entry.setdefault('grid', None)
            if revision != entry['revision']:
                raise ValueError('Points changed in another window. Refresh the list and try again.')
            places = entry['places']
            if clear_grid:
                if any(zone.get('cells') is not None for zone in entry['zones']):
                    raise ValueError('Delete or migrate all grid zones before clearing the field grid')
                entry['grid'] = None
            elif grid is not None:
                normalized_grid = field_grid(grid)
                grid_zones = [zone for zone in entry['zones'] if zone.get('cells') is not None]
                if grid_zones and entry['grid'] != normalized_grid:
                    raise ValueError('Delete or migrate all grid zones before changing the field grid')
                entry['grid'] = normalized_grid
            elif delete_zone_id is not None:
                zones = entry['zones']
                if not any(item['id'] == delete_zone_id for item in zones):
                    raise ValueError('Zone no longer exists')
                entry['zones'] = [item for item in zones if item['id'] != delete_zone_id]
            elif zone is not None:
                name = place_name(zone.get('name'))
                cells = grid_cells(zone.get('cells'))
                if not entry['grid']:
                    raise ValueError('Stretch and save the field grid before creating zones')
                zone_id = str(zone.get('id') or uuid.uuid4())
                zones = entry['zones']
                if zone.get('id') and not any(item['id'] == zone_id for item in zones):
                    raise ValueError('Zone no longer exists')
                if any(item['name'].casefold() == name.casefold() and item['id'] != zone_id for item in zones):
                    raise ValueError('A zone with this name already exists on this map')
                aliases = zone.get('aliases', [])
                if not isinstance(aliases, list) or any(not isinstance(item, str) or len(item) > 80 for item in aliases):
                    raise ValueError('Zone aliases must be short text items')
                entry['zones'] = sorted([item for item in zones if item['id'] != zone_id] + [{
                    'id': zone_id, 'name': name, 'aliases': [item.strip() for item in aliases if item.strip()],
                    'can_drive': bool(zone.get('can_drive')), 'cells': cells,
                }], key=lambda item: item['name'].casefold())
            elif delete_id is not None:
                if not any(p['id'] == delete_id for p in places):
                    raise ValueError('Point no longer exists')
                places = [p for p in places if p['id'] != delete_id]
            else:
                name = place_name(point.get('name'))
                pose = {key: float(point[key]) for key in ('x', 'y', 'yaw')}
                if not all(math.isfinite(value) for value in pose.values()):
                    raise ValueError('Point coordinates must be finite')
                point_id = str(point.get('id') or uuid.uuid4())
                if point.get('id') and not any(p['id'] == point_id for p in places):
                    raise ValueError('Point no longer exists')
                if any(p['name'].casefold() == name.casefold() and p['id'] != point_id for p in places):
                    raise ValueError('A point with this name already exists on this map')
                places = [p for p in places if p['id'] != point_id]
                places.append({'id': point_id, 'name': name, **pose})
            entry.update(revision=entry['revision'] + 1,
                         places=sorted(places, key=lambda p: p['name'].casefold()))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.named-places-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            return entry


class NamedPlacesMixin:
    def init_named_places(self):
        from rover_interfaces.srv import NamedPlaces
        from std_msgs.msg import String

        self.declare_parameter('named_places_file', '~/.config/sverk-rover/named_places.json')
        self.declare_parameter('named_places_service', '/rover/named_places')
        self.declare_parameter('robot_grid_pose_topic', '/rover/grid_pose')
        self.declare_parameter('robot_grid_pose_publish_hz', 5.0)
        self.declare_parameter('vlm_analyze_service', '/vlm/analyze_frame')
        # VLM runs on a separate computer and may need several seconds per frame.
        self.declare_parameter('vlm_analyze_timeout_sec', 45.0)
        self.declare_parameter('vlm_analyze_retry_interval_sec', 1.0)
        self._places_store = NamedPlacesStore(self.get_parameter('named_places_file').value)
        self._places_instance = uuid.uuid4().hex
        self._places_map_cache = {}
        self._places_prepared = None
        self._places_runtime_map_id = None
        self._zone_inspection = {
            'id': None, 'state': 'idle',
            'message': 'Choose a no-drive zone to test its inspection route.',
            'zone_name': '', 'map': '', 'route': [], 'current_index': None,
            'qr_codes': [], 'scan_index': None, 'road_state': 'unknown',
            'stop_after_scan': False, 'target_obstacle': '', 'vlm_result': None,
            'blocked_cells': [], 'target_obstacle_cell': None,
            'target_qr_candidates': [], 'target_qr_candidate_index': 0,
            'target_qr_current_side': None, 'alternate_path': [],
            'alternate_path_index': None, 'log': [], 'started_at': None,
            'return_to_start': False, 'return_wait_sec': 0.0,
            'return_state': 'idle', 'return_point': 'старт',
            'completion_state': None, 'completion_message': '',
            'direction': 'clockwise',
        }
        self._places_service = self.create_service(
            NamedPlaces, str(self.get_parameter('named_places_service').value), self._places_callback)
        self._robot_grid_pose_publisher = self.create_publisher(
            String, str(self.get_parameter('robot_grid_pose_topic').value), 10
        )
        publish_hz = max(0.2, float(self.get_parameter('robot_grid_pose_publish_hz').value))
        self.create_timer(1.0 / publish_hz, self._publish_robot_grid_pose)

    def _places_callback(self, request, response):
        try:
            data = self.named_places_command(request.command, json.loads(request.request_json or '{}'))
            response.success = True
            response.data_json = json.dumps(data, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            response.success = False
            response.message = str(exc)
            response.data_json = '{}'
        return response

    def _publish_robot_grid_pose(self):
        import rclpy
        from std_msgs.msg import String

        map_name = str(getattr(self, '_navigation_map', '') or '')
        status = self.zone_inspection_payload()
        if status.get('map'):
            map_name = str(status['map'])
        if not map_name or not hasattr(self, 'navigation_tf'):
            return
        try:
            transform = self.navigation_tf.lookup_transform(
                self.navigation_map_frame, 'base_link', rclpy.time.Time(),
            )
            stamp_age = (
                self.get_clock().now().nanoseconds
                - rclpy.time.Time.from_msg(transform.header.stamp).nanoseconds
            ) / 1e9
            if abs(stamp_age) >= 3.0:
                return
            rotation = transform.transform.rotation
            yaw = math.atan2(
                2 * (rotation.w * rotation.z + rotation.x * rotation.y),
                1 - 2 * (rotation.y * rotation.y + rotation.z * rotation.z),
            )
            x, y = transform.transform.translation.x, transform.transform.translation.y
            grid = self.named_places_payload(map_name).get('grid')
            if not grid:
                return
            cell = grid_cell_at_point(grid, x, y)
            message = String()
            message.data = json.dumps({
                'map': map_name,
                'frame_id': self.navigation_map_frame,
                'timestamp': self.get_clock().now().nanoseconds / 1e9,
                'cell': cell,
                'pose': {'x': x, 'y': y, 'yaw_rad': yaw, 'yaw_deg': math.degrees(yaw)},
                'view_direction': {'x': math.cos(yaw), 'y': math.sin(yaw)},
            }, ensure_ascii=False)
            self._robot_grid_pose_publisher.publish(message)
        except Exception:
            # Localization and the calibrated field grid are optional at startup.
            return

    def _places_map_id(self, map_name):
        path = self._resolve_map_yaml(map_name)
        metadata = yaml.safe_load(path.read_text(encoding='utf-8'))
        image = self._resolve_map_image(path, metadata)
        stamp = (str(path), path.stat().st_mtime_ns, image.stat().st_mtime_ns, image.stat().st_size)
        cached = self._places_map_cache.get(stamp)
        if cached is None:
            # Identical archive copies share points, but overwriting current/map.yaml
            # with another scan never silently reuses coordinates from the old map.
            geometry = {k: v for k, v in metadata.items() if k != 'image'}
            digest = hashlib.sha256(json.dumps(geometry, sort_keys=True).encode())
            with image.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            cached = digest.hexdigest()
            self._places_map_cache = {stamp: cached}
        return cached

    def named_places_payload(self, map_name):
        map_id = self._places_map_id(map_name)
        return {'map': map_name, 'map_id': map_id, **self._places_store.get(map_id)}

    def _places_odom(self):
        with self._lock:
            pose = self._pose_payload(self._odom)
            age = time.monotonic() - self._topic_state['odom'].received_monotonic
        if not pose or age > 2.0:
            raise RuntimeError('Fresh odometry is required. Check rover bringup.')
        if any(abs(pose.get(key, 0)) > limit for key, limit in [('vx', 0.02), ('vy', 0.02), ('wz', 0.05)]):
            raise RuntimeError('Stop the rover before confirming or using the initial pose.')
        return pose

    def _places_preparation(self):
        prepared = self._places_prepared
        if not prepared or prepared['generation'] != self._navigation_generation:
            raise RuntimeError('Select a map and confirm the initial pose in the web interface first.')
        if time.monotonic() > prepared['expires']:
            raise RuntimeError('Initial pose confirmation expired. Confirm it again in the web interface.')
        odom = self._places_odom()
        before = prepared['odom']
        angle = math.atan2(math.sin(odom['yaw'] - before['yaw']), math.cos(odom['yaw'] - before['yaw']))
        if (odom['frame_id'] != before['frame_id']
                or math.hypot(odom['x'] - before['x'], odom['y'] - before['y']) > 0.05
                or abs(angle) > math.radians(5)):
            raise RuntimeError('Rover moved after initial pose confirmation. Confirm its position again.')
        if prepared['map_id'] != self._places_map_id(prepared['map']):
            raise RuntimeError('Map changed. Confirm the map and initial pose again.')
        return prepared

    def update_named_places(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected an object')
        action = request.get('action', 'save')
        if action in {'navigate', 'status', 'cancel'}:
            return self.named_places_command(action, request)
        with self._navigation_control_lock:
            map_name = str(request.get('map') or '')
            map_id = self._places_map_id(map_name)
            if action == 'prepare':
                self._assert_navigation_runtime_idle()
                initial = self._navigation_pose(request.get('initial_pose'), 'initial_pose')
                self._places_prepared = {
                    'map': map_name, 'map_id': map_id, 'initial_pose': initial,
                    'odom': self._places_odom(), 'generation': self._navigation_generation,
                    'expires': time.monotonic() + 300,
                }
                return {'prepared': True, 'map': map_name, 'expires_in_sec': 300}
            if request.get('map_id') != map_id:
                raise ValueError('Map changed. Refresh points before saving.')
            if action in {'save_zone', 'delete_zone', 'save_grid', 'clear_grid'}:
                self._assert_navigation_runtime_idle()
            if action == 'save':
                self._places_store.update(map_id, request.get('revision'), point=request.get('point', {}))
            elif action == 'delete':
                self._places_store.update(map_id, request.get('revision'), delete_id=request.get('id', ''))
            elif action == 'save_zone':
                self._places_store.update(map_id, request.get('revision'), zone=request.get('zone', {}))
            elif action == 'delete_zone':
                self._places_store.update(map_id, request.get('revision'), delete_zone_id=request.get('id', ''))
            elif action == 'save_grid':
                self._places_store.update(map_id, request.get('revision'), grid=request.get('grid', {}))
            elif action == 'clear_grid':
                self._places_store.update(map_id, request.get('revision'), clear_grid=True)
            else:
                raise ValueError('Unknown named points operation')
            return self.named_places_payload(map_name)

    def navigation_map_with_zones(self, map_name):
        """Generate a private map copy whose no-drive zones are occupied cells for Nav2."""
        payload = self.named_places_payload(map_name)
        blocked = [zone for zone in payload['zones'] if not zone['can_drive']]
        source = self._resolve_map_yaml(map_name)
        if not blocked:
            return source
        metadata = yaml.safe_load(source.read_text(encoding='utf-8')) or {}
        image_path = self._resolve_map_image(source, metadata)
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError(f'Could not read map image {image_path.name}')
        resolution = float(metadata['resolution'])
        origin = metadata.get('origin', [0, 0, 0])
        ox, oy, yaw = (float(origin[0]), float(origin[1]), float(origin[2] if len(origin) > 2 else 0))
        height = image.shape[0]
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        polygons = []
        for zone in blocked:
            for corners in zone_geometry(zone, payload.get('grid')):
                pixels = []
                for corner in corners:
                    dx, dy = corner['x'] - ox, corner['y'] - oy
                    local_x = (cos_yaw * dx + sin_yaw * dy) / resolution
                    local_y = (-sin_yaw * dx + cos_yaw * dy) / resolution
                    pixels.append([round(local_x), round(height - local_y)])
                polygons.append(np.array(pixels, dtype=np.int32))
        cv2.fillPoly(image, polygons, color=0 if not int(metadata.get('negate', 0)) else 255)
        root = self._places_store.path.parent / 'navigation_keepout'
        root.mkdir(parents=True, exist_ok=True)
        suffix = f"{payload['map_id'][:12]}-{payload['revision']}"
        mask_image = root / f'{suffix}.pgm'
        mask_yaml = root / f'{suffix}.yaml'
        if not cv2.imwrite(str(mask_image), image):
            raise RuntimeError('Could not write navigation keepout map')
        navigation_metadata = dict(metadata)
        navigation_metadata['image'] = str(mask_image)
        mask_yaml.write_text(yaml.safe_dump(navigation_metadata, allow_unicode=True, sort_keys=False), encoding='utf-8')
        return mask_yaml

    def named_places_command(self, command, request):
        if not isinstance(request, dict):
            raise ValueError('Expected an object')
        with self._navigation_control_lock:
            runtime = self.navigation_status_payload()
            active_map = runtime['map'] if runtime['running'] and runtime['mode'] == 'navigation' else ''
            prepared = None
            hint = ''
            if not active_map:
                try:
                    prepared = self._places_preparation()
                    active_map = prepared['map']
                except RuntimeError as exc:
                    hint = str(exc)
            if command == 'list':
                maps = ([request['map']] if request.get('map') else
                        [active_map] if active_map else [m['path'] for m in self.maps_payload()['maps']])
                return {'active_map': active_map, 'hint': hint,
                        'maps': [self.named_places_payload(m) for m in maps]}
            if command == 'start_inspection':
                if not active_map:
                    raise RuntimeError(hint)
                if request.get('map') and request['map'] != active_map:
                    raise ValueError('Requested zone belongs to another map. Select and prepare that map first.')
                target_obstacle = str(request.get('target_obstacle') or 'any').strip()
                if target_obstacle != 'any' and target_obstacle not in VLM_OBSTACLE_CLASSES:
                    raise ValueError('Unknown target obstacle class')
                zones = self.named_places_payload(active_map)['zones']
                requested_name = place_name(request.get('name'))
                zone = next(
                    (
                        item for item in zones
                        if item['name'].casefold() == requested_name.casefold()
                        or any(alias.casefold() == requested_name.casefold()
                               for alias in item.get('aliases', []))
                    ),
                    None,
                )
                if zone is None:
                    raise ValueError(f'No zone named {requested_name!r} on the active map.')
                if zone['can_drive']:
                    raise ValueError('The selected zone must be marked as no-drive for inspection.')
                return {'inspection': self.start_zone_inspection({
                    'map': active_map, 'zone_id': zone['id'], 'target_obstacle': target_obstacle,
                })}
            if command == 'inspection_status':
                return {'inspection': self.zone_inspection_payload()}
            if command in {'status', 'cancel'}:
                token = {'instance': self._places_instance, 'generation': self._navigation_generation}
                if request.get('token') != token:
                    raise RuntimeError('This goal is no longer current (stopped, replaced or web restarted).')
                if command == 'cancel':
                    if runtime['goal_state'] in {'queued', 'sending', 'active', 'canceling'}:
                        runtime = self.cancel_navigation_goal()
                return {'token': token, 'navigation': runtime}
            if command != 'navigate':
                raise ValueError('Unknown named points command')
            if not active_map:
                raise RuntimeError(hint)
            if request.get('map') and request['map'] != active_map:
                raise ValueError('Requested point belongs to another map. Select and prepare that map first.')
            if self._motor_calibration_active:
                raise RuntimeError('Finish motor calibration first')
            points = self.named_places_payload(active_map)
            if runtime['running'] and self._places_runtime_map_id != points['map_id']:
                raise RuntimeError('Map on disk changed. Restart navigation on the new map first.')
            name = place_name(request.get('name'))
            point = next(
                (
                    item for item in points['places']
                    if item['name'].casefold() == name.casefold()
                    or any(alias.casefold() == name.casefold() for alias in item.get('aliases', []))
                ),
                None,
            )
            if point is None:
                raise ValueError(f'No point named {name!r} on the active map. Call list_named_places first.')
            goal = {key: point[key] for key in ('x', 'y', 'yaw')}
            if runtime['running']:
                if runtime['mode'] != 'navigation' or runtime['phase'] != 'running':
                    raise RuntimeError('Wait for Nav2; stop mapping before starting navigation.')
                if not runtime.get('map_pose'):
                    raise RuntimeError('Current map pose is unavailable. Check localization before moving.')
                runtime = self.send_navigation_goal({'goal': goal})
            else:
                runtime = self.start_navigation({'map': active_map,
                                                'initial_pose': prepared['initial_pose'], 'goal': goal})
                self._places_prepared = None
            return {'name': point['name'], 'map': active_map, 'goal': goal,
                    'token': {'instance': self._places_instance, 'generation': self._navigation_generation},
                    'navigation': runtime}

    def zone_inspection_payload(self):
        with self._lock:
            result = dict(self._zone_inspection)
            result['route'] = [dict(point) for point in result['route']]
            result['qr_codes'] = list(result['qr_codes'])
            result['blocked_cells'] = [dict(cell) for cell in result['blocked_cells']]
            result['target_obstacle_cell'] = (
                dict(result['target_obstacle_cell'])
                if result['target_obstacle_cell'] else None
            )
            result['target_qr_candidates'] = [dict(point) for point in result['target_qr_candidates']]
            result['target_qr_current_side'] = (
                dict(result['target_qr_current_side'])
                if result['target_qr_current_side'] else None
            )
            result['alternate_path'] = [dict(point) for point in result['alternate_path']]
            result['log'] = [dict(item) for item in result['log']]
            return result

    def _set_zone_inspection(self, **changes):
        return_to_start = False
        inspection_id = None
        with self._lock:
            self._zone_inspection.update(changes)
            requested_state = changes.get('state')
            if (
                requested_state in ZONE_INSPECTION_AUTOMATIC_TERMINAL_STATES
                and self._zone_inspection.get('return_to_start')
                and self._zone_inspection.get('return_state') == 'pending'
            ):
                self._zone_inspection.update({
                    'state': 'waiting_to_return',
                    'completion_state': requested_state,
                    'completion_message': str(changes.get(
                        'message', self._zone_inspection.get('message', '')
                    )),
                    'return_state': 'waiting',
                    'message': 'Inspection finished. Preparing the safe route back to "старт".',
                })
                return_to_start = True
                inspection_id = self._zone_inspection.get('id')
        if return_to_start and inspection_id:
            threading.Thread(
                target=self._return_zone_inspection_to_start,
                args=(inspection_id,),
                name='rover-zone-inspection-return',
                daemon=True,
            ).start()

    @staticmethod
    def _named_place(payload, name):
        normalized = place_name(name).casefold()
        return next(
            (
                item for item in payload['places']
                if item['name'].casefold() == normalized
                or any(alias.casefold() == normalized for alias in item.get('aliases', []))
            ),
            None,
        )

    def _return_zone_inspection_to_start(self, inspection_id):
        """Reload Nav2's generated no-drive map before going back to start."""
        status = self.zone_inspection_payload()
        if status.get('id') != inspection_id or status.get('state') != 'waiting_to_return':
            return
        wait_sec = max(0.0, min(30.0, float(status.get('return_wait_sec', 0.0))))
        if wait_sec:
            self._zone_inspection_log('Waiting at the inspection result before returning to start.', seconds=wait_sec)
            deadline = time.monotonic() + wait_sec
            while time.monotonic() < deadline:
                current = self.zone_inspection_payload()
                if current.get('id') != inspection_id or current.get('state') != 'waiting_to_return':
                    return
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        status = self.zone_inspection_payload()
        if status.get('id') != inspection_id or status.get('state') != 'waiting_to_return':
            return
        try:
            places = self.named_places_payload(status['map'])
            start = self._named_place(places, status.get('return_point', 'старт'))
            if start is None:
                raise RuntimeError('Named point "старт" is not configured for this map')
            runtime = self.navigation_status_payload()
            current_pose = runtime.get('map_pose')
            if not current_pose:
                raise RuntimeError('Current map pose is unavailable, so a safe return cannot be started')
            goal = {key: start[key] for key in ('x', 'y', 'yaw')}
            if (
                runtime.get('running')
                and runtime.get('mode') == 'navigation'
                and runtime.get('phase') == 'running'
                and runtime.get('map') == status['map']
            ):
                # The inspection has already canceled its active goal. Reuse
                # this Nav2 stack rather than restarting it for the return.
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    current_runtime = self.navigation_status_payload()
                    if current_runtime.get('goal_state') not in {
                            'queued', 'sending', 'active', 'canceling'}:
                        break
                    time.sleep(0.15)
                else:
                    raise RuntimeError('Previous inspection goal did not cancel before returning')
                self.send_navigation_goal({'goal': goal})
            else:
                if runtime.get('running') or self._node_is_visible('/bt_navigator'):
                    self.stop_navigation_runtime()
                deadline = time.monotonic() + 12.0
                while (
                    self.navigation_status_payload().get('running')
                    or self._node_is_visible('/bt_navigator')
                ) and time.monotonic() < deadline:
                    time.sleep(0.2)
                if self.navigation_status_payload().get('running') or self._node_is_visible('/bt_navigator'):
                    raise RuntimeError('Nav2 did not stop before the map could be refreshed')
                self.start_navigation({
                    'map': status['map'], 'initial_pose': current_pose, 'goal': goal,
                })
            self._set_zone_inspection(
                state='returning_to_start', return_state='active', return_goal=goal,
                message='Returning to "старт" using the updated no-drive map.',
            )
            self._zone_inspection_log(
                'Inspection route is complete; returning to start on the updated no-drive map.',
                return_point=start['name'], blocked_cells=len(status.get('blocked_cells', [])),
            )
            deadline = time.monotonic() + 180.0
            while time.monotonic() < deadline:
                current = self.zone_inspection_payload()
                if current.get('id') != inspection_id or current.get('state') != 'returning_to_start':
                    return
                goal_state = self.navigation_status_payload().get('goal_state')
                if goal_state == 'succeeded':
                    self._set_zone_inspection(
                        state='returned', return_state='succeeded',
                        message='Inspection complete. Rover returned to "старт".',
                    )
                    self._zone_inspection_log('Rover returned to start.', return_point=start['name'])
                    return
                if goal_state not in {'queued', 'sending', 'active'}:
                    raise RuntimeError(f'Navigation back to start ended as {goal_state}')
                time.sleep(0.25)
            raise RuntimeError('Timed out while returning to start')
        except Exception as exc:
            self._set_zone_inspection(
                state='return_failed', return_state='failed',
                message=f'Inspection finished, but return to "старт" failed: {exc}',
            )
            self._zone_inspection_log('Return to start failed.', error=str(exc))

    def _zone_inspection_log(self, message, **details):
        event = {'at': time.time(), 'message': message, **details}
        with self._lock:
            events = list(self._zone_inspection.get('log', []))
            events.append(event)
            self._zone_inspection['log'] = events[-100:]

    @staticmethod
    def _vlm_classification(message):
        raw = str(message or '').strip()
        text = raw.lower()
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                values = [payload.get(key, '') for key in (
                    'class', 'obstacle_class', 'result', 'label', 'message'
                )]
                observation = payload.get('observation')
                if isinstance(observation, dict):
                    values.extend(observation.get(key, '') for key in (
                        'event_type', 'class', 'obstacle_class', 'result', 'label'
                    ))
                text = ' '.join(str(value) for value in values).lower()
        except (TypeError, ValueError):
            pass
        if text.strip() in {'none', 'null', 'no_obstacle', 'no obstacle'}:
            return 'none'
        for obstacle_class in VLM_OBSTACLE_CLASSES:
            if obstacle_class in text:
                return obstacle_class
        return 'unknown'

    def _analyze_blocked_cell_with_vlm(self):
        service = str(self.get_parameter('vlm_analyze_service').value)
        timeout_sec = max(1.0, float(self.get_parameter('vlm_analyze_timeout_sec').value))
        retry_interval_sec = max(
            0.1, float(self.get_parameter('vlm_analyze_retry_interval_sec').value)
        )
        handle = self._ensure_service_client(service, 'std_srvs/srv/Trigger')
        if not handle.client.wait_for_service(timeout_sec=2.0):
            raise RuntimeError(f'VLM service {service} is unavailable')
        started = time.monotonic()
        attempts = 0
        while True:
            remaining_sec = timeout_sec - (time.monotonic() - started)
            if remaining_sec <= 0.0:
                raise RuntimeError(
                    f'VLM did not produce a frame result within {timeout_sec:.0f} seconds'
                )
            attempts += 1
            response = self._wait_for_future(
                handle.client.call_async(handle.srv_class.Request()),
                timeout_sec=remaining_sec,
                label='VLM analyze_frame',
            )
            if response is None:
                raise RuntimeError('VLM analyze_frame returned no response')
            message = str(response.message or '')
            if bool(response.success):
                return {
                    'service': service,
                    'classification': self._vlm_classification(message),
                    'message': message,
                    'duration_sec': round(time.monotonic() - started, 3),
                    'attempts': attempts,
                }
            transient = message.casefold()
            if 'busy' not in transient and 'camera frame unavailable' not in transient:
                raise RuntimeError(message or 'VLM analysis failed')
            self._zone_inspection_log(
                'VLM is temporarily unavailable; retrying.',
                attempt=attempts, response=message,
            )
            time.sleep(min(retry_interval_sec, remaining_sec))

    @staticmethod
    def _zone_major_cells(zone):
        return {
            (cell['row'] // GRID_SUBCELLS, cell['column'] // GRID_SUBCELLS)
            for cell in zone.get('cells', [])
        }

    def _save_obstacle_cell(self, status, obstacle_class):
        """Persist the cell in front of the rover as a four-subcell no-drive zone."""
        current_index = int(status['current_index'])
        if current_index >= len(status['route']) - 1:
            raise RuntimeError('There is no next grid cell to mark as blocked')
        blocked_point = status['route'][current_index + 1]
        blocked_cell = (blocked_point['major_row'], blocked_point['major_column'])
        places = self.named_places_payload(status['map'])
        grid = places.get('grid')
        if not grid:
            raise RuntimeError('The field grid is required to remember an obstacle')
        subcells = [
            {'row': blocked_cell[0] * GRID_SUBCELLS + row_offset,
             'column': blocked_cell[1] * GRID_SUBCELLS + column_offset}
            for row_offset in range(GRID_SUBCELLS)
            for column_offset in range(GRID_SUBCELLS)
        ]
        existing = next(
            (
                zone for zone in places['zones']
                if not zone.get('can_drive') and zone.get('cells') == subcells
            ),
            None,
        )
        if existing:
            saved = places
        else:
            label = obstacle_class.replace('_', ' ')
            saved = self._places_store.update(
                places['map_id'], places['revision'],
                zone={
                    'name': f'Obstacle {label} {blocked_cell[0] + 1}-{blocked_cell[1] + 1}',
                    'aliases': [obstacle_class], 'can_drive': False, 'cells': subcells,
                },
            )
        forbidden = set()
        for zone in saved['zones']:
            if not zone.get('can_drive'):
                forbidden.update(self._zone_major_cells(zone))
        return grid, forbidden, {
            'x': blocked_point['x'], 'y': blocked_point['y'],
            'major_row': blocked_cell[0], 'major_column': blocked_cell[1],
            'class': obstacle_class,
        }

    def _target_qr_candidates(self, grid, forbidden, current_side, obstacle):
        """Return accessible sides of the obstacle, nearest side first."""
        candidates = []
        obstacle_cell = (obstacle['major_row'], obstacle['major_column'])
        current_cell = (current_side['major_row'], current_side['major_column'])
        for row_delta, column_delta in ((-1, 0), (0, 1), (1, 0), (0, -1)):
            cell = (obstacle_cell[0] + row_delta, obstacle_cell[1] + column_delta)
            if (cell == current_cell or cell in forbidden
                    or not 0 <= cell[0] < GRID_MAJOR_CELLS
                    or not 0 <= cell[1] < GRID_MAJOR_CELLS):
                continue
            try:
                route = major_grid_detour(
                    grid, current_side, grid_major_center(grid, cell[0], cell[1]), forbidden
                )
            except ValueError:
                continue
            candidate = route[-1]
            candidate['yaw'] = math.atan2(
                obstacle['y'] - candidate['y'], obstacle['x'] - candidate['x']
            )
            candidate['route_length'] = len(route)
            candidates.append(candidate)
        return sorted(candidates, key=lambda point: (
            point['route_length'], point['major_row'], point['major_column']
        ))

    def _start_next_target_qr_side(self, status):
        """Navigate to the next untested side while keeping the obstacle off-limits."""
        candidate_index = int(status.get('target_qr_candidate_index') or 0)
        candidates = status.get('target_qr_candidates') or []
        if candidate_index >= len(candidates):
            return False
        candidate = dict(candidates[candidate_index])
        obstacle = status.get('target_obstacle_cell')
        current_side = status.get('target_qr_current_side') or status['route'][status['current_index']]
        places = self.named_places_payload(status['map'])
        grid = places.get('grid')
        forbidden = set()
        for zone in places['zones']:
            if not zone.get('can_drive'):
                forbidden.update(self._zone_major_cells(zone))
        route = major_grid_detour(grid, current_side, candidate, forbidden)[1:]
        if not route:
            return False
        route[-1]['yaw'] = math.atan2(
            obstacle['y'] - route[-1]['y'], obstacle['x'] - route[-1]['x']
        )
        self.send_navigation_goal({'goal': route[0]})
        self._set_zone_inspection(
            state='alternate_qr_moving', alternate_path=route, alternate_path_index=0,
            target_qr_candidate_index=candidate_index + 1,
            message=(
                f'Moving around the no-drive obstacle to QR scan side '
                f'{candidate_index + 2}/{len(candidates) + 1}.'
            ),
        )
        self._zone_inspection_log(
            'Moving to another side of the target obstacle for QR scan.',
            row=candidate['major_row'], column=candidate['major_column'],
        )
        return True

    def _remember_obstacle_and_reroute(self, status, obstacle_class):
        """Persist the blocked next cell and replace it with a free grid detour."""
        current_index = int(status['current_index'])
        grid, forbidden, blocked = self._save_obstacle_cell(status, obstacle_class)
        blocked_cell = (blocked['major_row'], blocked['major_column'])
        remaining = status['route'][current_index + 2:]
        if not remaining:
            return [], {'row': blocked_cell[0], 'column': blocked_cell[1], 'class': obstacle_class}
        detour = major_grid_detour(grid, status['route'][current_index], remaining[0], forbidden)
        route = status['route'][:current_index + 1] + detour[1:-1] + remaining
        return set_route_yaws(route), {
            'row': blocked_cell[0], 'column': blocked_cell[1], 'class': obstacle_class,
        }

    def _zone_inspection_qr_codes(self, after_count, timeout_sec=2.0):
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            payload = self.vision_qr_detections()
            if payload.get('message_count', 0) > after_count:
                codes = self._zone_inspection_qr_codes_from_payload(payload)
                if codes:
                    return codes
            time.sleep(0.15)
        return []

    @staticmethod
    def _zone_inspection_qr_codes_from_payload(payload):
        """Keep only QR detections that have successfully decoded text."""
        result = payload.get('result') or {}
        return [str(item['data']).strip() for item in result.get('codes', [])
                if isinstance(item, dict) and item.get('data') is not None
                and str(item['data']).strip()]

    def _start_zone_qr_scan(self, status, *, road_state='unknown'):
        """Holding the heading toward the next point, sample QR without turning."""
        self._set_zone_inspection(
            state='scanning', scan_index=0, road_state=road_state,
            stop_after_scan=False,
            message=(
                f'QR scan at point {status["current_index"] + 1}: '
                'holding the heading toward the next point.'
            ),
        )

    def _start_zone_blocked_approach(self, status, road_state):
        """Move closer to a reported obstacle before the local multi-angle QR scan."""
        self.start_motion({
            'kind': 'move', 'forward': 0.18, 'left': 0.0, 'speed': 0.12,
        })
        self._set_zone_inspection(
            state='approaching_qr', scan_index=None, road_state=road_state,
            stop_after_scan=True,
            message=(
                f'Obstacle is reported ahead at point {status["current_index"] + 1}; '
                'moving 18 cm closer before the QR scan.'
            ),
        )

    def _start_zone_blocked_scan(self, status):
        self._set_zone_inspection(
            state='blocked_scanning', scan_index=0, stop_after_scan=True,
            message=(
                f'Checking for QR near the obstacle at point '
                f'{status["current_index"] + 1}, view 1/4.'
            ),
        )

    def start_zone_inspection(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected an object')
        with self._navigation_control_lock:
            if self.zone_inspection_payload()['state'] in {
                    'starting', 'active', 'scanning', 'approaching_qr',
                    'blocked_scanning', 'blocked_turning', 'vlm_analyzing',
                    'alternate_qr_moving'}:
                raise RuntimeError('Zone inspection is already running')
            map_name = str(request.get('map') or '')
            target_obstacle = str(request.get('target_obstacle') or '').strip()
            if target_obstacle != 'any' and target_obstacle not in VLM_OBSTACLE_CLASSES:
                raise ValueError('Choose the target obstacle class before starting inspection')
            return_wait_sec = float(request.get('return_wait_sec', 0.0))
            if not math.isfinite(return_wait_sec) or not 0.0 <= return_wait_sec <= 30.0:
                raise ValueError('return_wait_sec must be between 0 and 30 seconds')
            direction = str(request.get('direction') or 'clockwise').strip().lower()
            if direction not in {'clockwise', 'counterclockwise'}:
                raise ValueError('Choose clockwise or counterclockwise inspection direction')
            payload = self.named_places_payload(map_name)
            zone = next((item for item in payload['zones'] if item['id'] == str(request.get('zone_id') or '')), None)
            if zone is None:
                raise ValueError('Choose a saved zone for inspection')
            if zone['can_drive']:
                raise ValueError('Inspection is available only for a no-drive zone')
            runtime = self.navigation_status_payload()
            if runtime['running']:
                if runtime['mode'] != 'navigation' or runtime['phase'] != 'running' or runtime['map'] != map_name:
                    raise RuntimeError('Nav2 must be running for the selected map')
                if not runtime.get('map_pose'):
                    raise RuntimeError('Current map pose is unavailable. Check localization before moving.')
                route = inspection_grid_route(
                    zone, payload.get('grid'), runtime['map_pose'], direction,
                )
                self.send_navigation_goal({'goal': route[0]})
            else:
                prepared = self._places_preparation()
                if prepared['map'] != map_name:
                    raise RuntimeError('Prepare the selected map and initial pose before inspection.')
                route = inspection_grid_route(
                    zone, payload.get('grid'), prepared['initial_pose'], direction,
                )
                self.start_navigation({
                    'map': map_name,
                    'initial_pose': prepared['initial_pose'],
                    'goal': route[0],
                })
                self._places_prepared = None
            inspection_id = uuid.uuid4().hex
            self._set_zone_inspection(id=inspection_id, state='starting',
                                      message='Starting Nav2 and moving to inspection point 1.',
                                      zone_name=zone['name'], map=map_name, route=route,
                                      current_index=0, qr_codes=[], scan_index=None,
                                      road_state='unknown', stop_after_scan=False,
                                      target_obstacle=target_obstacle, vlm_result=None,
                                      blocked_cells=[], target_obstacle_cell=None,
                                      target_qr_candidates=[], target_qr_candidate_index=0,
                                      target_qr_current_side=None, alternate_path=[],
                                      alternate_path_index=None, log=[],
                                      started_at=time.time(), return_to_start=True,
                                      return_wait_sec=return_wait_sec,
                                      return_state='pending', return_point='старт',
                                      completion_state=None, completion_message='',
                                      direction=direction)
            threading.Thread(target=self._zone_inspection_worker, args=(inspection_id,), name='rover-zone-inspection', daemon=True).start()
            target_label = vlm_obstacle_label(target_obstacle)
            self.record_activity('navigation', 'Zone inspection started', {
                'static_object': zone['name'],
                'dynamic_object': target_label,
                'dynamic_object_class': target_obstacle,
                'direction': direction,
            })
            self._zone_inspection_log(
                (
                    f'Inspection started: circling static object "{zone["name"]}"; '
                    f'looking for dynamic object "{target_label}" '
                    f'({target_obstacle}); direction: {direction}.'
                ),
                static_object=zone['name'],
                dynamic_object=target_label,
                dynamic_object_class=target_obstacle,
                direction=direction,
            )
            return self.zone_inspection_payload()

    def stop_zone_inspection(self):
        with self._navigation_control_lock:
            status = self.zone_inspection_payload()
            if status['state'] not in {
                    'starting', 'active', 'scanning', 'approaching_qr',
                    'blocked_scanning', 'blocked_turning', 'vlm_analyzing',
                    'alternate_qr_moving'}:
                raise RuntimeError('Zone inspection is not running')
            self._set_zone_inspection(
                state='canceled', return_to_start=False,
                return_state='canceled', message='Inspection canceled by the operator.',
            )
            if self.motion_status_payload()['running']:
                self.stop_motion()
            runtime = self.navigation_status_payload()
            if runtime['goal_state'] in {'queued', 'sending', 'active', 'canceling'}:
                self.cancel_navigation_goal()
            self.record_activity('navigation', 'Zone inspection canceled', {'zone': status['zone_name']})
            return self.zone_inspection_payload()

    def _zone_inspection_worker(self, inspection_id):
        last_qr_message_count = self.vision_qr_detections().get('message_count', 0)
        while True:
            status = self.zone_inspection_payload()
            if status['id'] != inspection_id or status['state'] not in {
                    'starting', 'active', 'scanning', 'approaching_qr',
                    'blocked_scanning', 'blocked_turning', 'vlm_analyzing',
                    'alternate_qr_moving'}:
                return
            if status['state'] == 'vlm_analyzing':
                try:
                    vlm = self._analyze_blocked_cell_with_vlm()
                except Exception as exc:
                    self._zone_inspection_log('VLM analysis failed', error=str(exc))
                    self._set_zone_inspection(
                        state='blocked',
                        message=f'Road is blocked, but VLM analysis failed: {exc}',
                    )
                    return
                classification = vlm['classification']
                self._zone_inspection_log(
                    'VLM analysis completed', classification=classification,
                    response=vlm['message'], duration_sec=vlm['duration_sec'],
                )
                self._set_zone_inspection(vlm_result=vlm)
                if classification == 'none':
                    next_index = status['current_index'] + 1
                    if next_index >= len(status['route']):
                        self._set_zone_inspection(
                            state='completed',
                            message='VLM confirmed no obstacle; perimeter inspection completed.',
                        )
                        return
                    self.send_navigation_goal({'goal': status['route'][next_index]})
                    self._set_zone_inspection(
                        state='active', current_index=next_index,
                        message='VLM confirmed no obstacle. Continuing to the next inspection point.',
                    )
                    continue
                if classification == status['target_obstacle'] or status['target_obstacle'] == 'any':
                    try:
                        grid, forbidden, obstacle = self._save_obstacle_cell(status, classification)
                        current_side = dict(status['route'][status['current_index']])
                        candidates = self._target_qr_candidates(
                            grid, forbidden, current_side, obstacle
                        )
                    except Exception as exc:
                        self._zone_inspection_log('Could not mark target obstacle as no-drive', error=str(exc))
                        self._set_zone_inspection(
                            state='blocked',
                            message=f'Target obstacle was detected, but could not be marked as no-drive: {exc}',
                        )
                        return
                    obstacle_cell = {
                        'row': obstacle['major_row'], 'column': obstacle['major_column'],
                        'class': classification,
                    }
                    self._set_zone_inspection(
                        blocked_cells=status['blocked_cells'] + [obstacle_cell],
                        target_obstacle_cell=obstacle,
                        target_qr_candidates=candidates,
                        target_qr_candidate_index=0,
                        target_qr_current_side=current_side,
                    )
                    self._zone_inspection_log(
                        'Target obstacle was saved as a no-drive cell; starting local QR search.',
                        **obstacle_cell, alternate_sides=len(candidates),
                    )
                    self._start_zone_blocked_approach(status, status['road_state'])
                    continue
                if classification == 'unknown':
                    self._set_zone_inspection(
                        state='blocked',
                        message='VLM returned an unknown obstacle class; inspection stopped safely.',
                    )
                    return
                try:
                    route, blocked_cell = self._remember_obstacle_and_reroute(status, classification)
                    if len(route) <= status['current_index'] + 1:
                        self._set_zone_inspection(
                            state='completed', route=route,
                            blocked_cells=status['blocked_cells'] + [blocked_cell],
                            message='Non-target obstacle was saved; no contour points remain.',
                        )
                        return
                    next_index = status['current_index'] + 1
                    self.send_navigation_goal({'goal': route[next_index]})
                    self._set_zone_inspection(
                        state='active', route=route, current_index=next_index,
                        blocked_cells=status['blocked_cells'] + [blocked_cell],
                        message=(
                            f'Non-target {classification} was saved as a no-drive cell. '
                            'Continuing via a free grid detour.'
                        ),
                    )
                    self._zone_inspection_log('Route rebuilt around non-target obstacle', **blocked_cell)
                except Exception as exc:
                    self._zone_inspection_log('Could not rebuild route around obstacle', error=str(exc))
                    self._set_zone_inspection(
                        state='blocked', message=f'Obstacle saved, but no safe detour is available: {exc}',
                    )
                continue
            if status['state'] == 'scanning':
                codes = self._zone_inspection_qr_codes(
                    self.vision_qr_detections().get('message_count', 0), timeout_sec=3.0)
                if codes:
                    self._set_zone_inspection(
                        state='succeeded', qr_codes=codes,
                        message='QR with text was detected. Perimeter inspection completed.',
                    )
                    self.record_activity('vision', 'QR found during zone inspection', {
                        'zone': status['zone_name'], 'codes': codes,
                    })
                    return
                if status.get('stop_after_scan'):
                    self._set_zone_inspection(
                        state='blocked', scan_index=None,
                        message=(
                            'Road is blocked ahead. The contour stopped at the current cell; '
                            'no QR text was detected during the local check.'
                        ),
                    )
                    self.record_activity('navigation', 'Zone inspection stopped by road state', {
                        'zone': status['zone_name'],
                        'point': status['current_index'] + 1,
                        'road_state': status.get('road_state'),
                    })
                    return
                # A code observed while stopped belongs to that completed scan.
                # Do not let its last published frame finish the next transit.
                last_qr_message_count = self.vision_qr_detections().get('message_count', 0)
                next_index = status['current_index'] + 1
                if next_index >= len(status['route']):
                    self._set_zone_inspection(
                        state='completed', current_index=len(status['route']) - 1,
                        message='Full clockwise contour completed. QR code was not detected.',
                    )
                    self.record_activity('navigation', 'Zone inspection completed', {
                        'zone': status['zone_name'],
                    })
                    return
                try:
                    self.send_navigation_goal({'goal': status['route'][next_index]})
                    self._set_zone_inspection(
                        state='active', current_index=next_index, scan_index=None,
                        message=f'Moving to inspection point {next_index + 1}/{len(status["route"])}.',
                    )
                except Exception as exc:
                    self._set_zone_inspection(
                        state='error', current_index=status['current_index'],
                        message=f'Could not start inspection point {next_index + 1}: {exc}',
                    )
                    return
                continue
            if status['state'] == 'approaching_qr':
                motion = self.motion_status_payload()
                if motion['running']:
                    time.sleep(0.15)
                    continue
                # The gateway records a finished child process on its 1 Hz
                # maintenance tick. Wait for that definitive return code.
                if motion['return_code'] is None:
                    time.sleep(0.15)
                    continue
                if motion['return_code'] != 0:
                    self._set_zone_inspection(
                        state='error',
                        message='Could not safely move closer to the reported obstacle.',
                    )
                    return
                self._start_zone_blocked_scan(status)
                continue
            if status['state'] == 'alternate_qr_moving':
                runtime = self.navigation_status_payload()
                goal_state = runtime.get('goal_state')
                if goal_state in {'queued', 'sending', 'active'}:
                    time.sleep(0.15)
                    continue
                if goal_state != 'succeeded':
                    self._set_zone_inspection(
                        state='error',
                        message=f'Could not reach another QR scan side: navigation goal is {goal_state}.',
                    )
                    return
                path_index = int(status['alternate_path_index']) + 1
                path = status['alternate_path']
                if path_index < len(path):
                    try:
                        self.send_navigation_goal({'goal': path[path_index]})
                        self._set_zone_inspection(
                            alternate_path_index=path_index,
                            message='Continuing around the target obstacle to the next QR scan side.',
                        )
                    except Exception as exc:
                        self._set_zone_inspection(
                            state='error', message=f'Could not continue to another QR scan side: {exc}',
                        )
                    continue
                self._set_zone_inspection(
                    state='blocked_scanning', scan_index=0,
                    target_qr_current_side=dict(path[-1]), alternate_path=[],
                    alternate_path_index=None,
                    message='Checking for QR from another side of the no-drive obstacle, view 1/4.',
                )
                continue
            if status['state'] == 'blocked_turning':
                motion = self.motion_status_payload()
                if motion['running']:
                    time.sleep(0.15)
                    continue
                if motion['return_code'] is None:
                    time.sleep(0.15)
                    continue
                if motion['return_code'] != 0:
                    self._set_zone_inspection(
                        state='error',
                        message='Could not turn for the QR scan near the obstacle.',
                    )
                    return
                view_number = int(status['scan_index']) + 1
                self._set_zone_inspection(
                    state='blocked_scanning',
                    message=(
                        f'Checking for QR near the obstacle at point '
                        f'{status["current_index"] + 1}, view {view_number}/4.'
                    ),
                )
                continue
            if status['state'] == 'blocked_scanning':
                codes = self._zone_inspection_qr_codes(
                    self.vision_qr_detections().get('message_count', 0), timeout_sec=3.0)
                if codes:
                    self._set_zone_inspection(
                        state='succeeded', qr_codes=codes,
                        message='QR with text was detected near the obstacle. Perimeter inspection completed.',
                    )
                    self.record_activity('vision', 'QR found near obstacle during zone inspection', {
                        'zone': status['zone_name'], 'codes': codes,
                    })
                    return
                scan_index = int(status['scan_index'])
                if scan_index >= len(blocked_turns):
                    try:
                        if status.get('target_obstacle_cell') and self._start_next_target_qr_side(status):
                            continue
                    except Exception as exc:
                        self._zone_inspection_log(
                            'Could not reach another side of the target obstacle.', error=str(exc)
                        )
                    self._set_zone_inspection(
                        state='blocked', scan_index=None,
                        message=(
                            'Road is blocked ahead. The rover moved closer and checked four views; '
                            'no QR text was detected.'
                        ),
                    )
                    self.record_activity('navigation', 'Zone inspection stopped by road state', {
                        'zone': status['zone_name'],
                        'point': status['current_index'] + 1,
                        'road_state': status.get('road_state'),
                    })
                    return
                degrees = blocked_turns[scan_index]
                try:
                    self.start_motion({
                        'kind': 'turn', 'degrees': degrees,
                        'speed': 0.25, 'tolerance_deg': 5.0,
                    })
                    self._set_zone_inspection(
                        state='blocked_turning', scan_index=scan_index + 1,
                        message=(
                            f'Changing QR scan view near the obstacle: '
                            f'turn {degrees:+.0f} degrees.'
                        ),
                    )
                except Exception as exc:
                    self._set_zone_inspection(
                        state='error', message=f'Could not turn for QR scan: {exc}',
                    )
                    return
                continue
            runtime = self.navigation_status_payload()
            goal_state = runtime.get('goal_state')
            if goal_state in {'queued', 'sending'}:
                self._set_zone_inspection(
                    state='starting',
                    message=f'Starting navigation to inspection point {status["current_index"] + 1}.',
                )
                time.sleep(0.25)
                continue
            if goal_state == 'succeeded':
                try:
                    road = self.road_state()
                    if road['fresh'] and road['state'] == 'blocked':
                        self._zone_inspection_log(
                            'Road observer reported a blocked corridor; continuing the inspection route.',
                            point=status['current_index'] + 1,
                        )
                    self._start_zone_qr_scan(status, road_state=road['state'])
                except Exception as exc:
                    self._set_zone_inspection(
                        state='error', current_index=status['current_index'],
                        message=f'Could not start QR scan: {exc}',
                    )
                    return
                continue
            if goal_state != 'active':
                self._set_zone_inspection(
                    state='error', current_index=status['current_index'],
                    message=f'Inspection stopped: waypoint route is {goal_state}.',
                )
                return
            qr_payload = self.vision_qr_detections()
            qr_count = qr_payload.get('message_count', 0)
            if qr_count > last_qr_message_count:
                last_qr_message_count = qr_count
                codes = self._zone_inspection_qr_codes_from_payload(qr_payload)
                if codes:
                    try:
                        self.cancel_navigation_goal()
                    except Exception:
                        # The goal may finish between reading its state and cancellation.
                        pass
                    self._set_zone_inspection(
                        state='succeeded', qr_codes=codes,
                        message='QR with text was detected while moving. Perimeter inspection completed.',
                    )
                    self.record_activity('vision', 'QR found while moving during zone inspection', {
                        'zone': status['zone_name'], 'codes': codes,
                    })
                    return
            self._set_zone_inspection(
                state='active',
                message=(
                    f'Moving to inspection point {status["current_index"] + 1}/'
                    f'{len(status["route"])}.'
                ),
            )
            time.sleep(0.15)
