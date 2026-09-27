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
            entry = self._read()['maps'].get(map_id, {'revision': 0, 'places': [], 'zones': []})
            return {**entry, 'places': list(entry.get('places', [])), 'zones': list(entry.get('zones', []))}

    def update(self, map_id, revision, *, point=None, delete_id=None, zone=None, delete_zone_id=None):
        with self.lock:
            data = self._read()
            entry = data['maps'].setdefault(map_id, {'revision': 0, 'places': [], 'zones': []})
            entry.setdefault('places', [])
            entry.setdefault('zones', [])
            if revision != entry['revision']:
                raise ValueError('Points changed in another window. Refresh the list and try again.')
            places = entry['places']
            if delete_zone_id is not None:
                zones = entry['zones']
                if not any(item['id'] == delete_zone_id for item in zones):
                    raise ValueError('Zone no longer exists')
                entry['zones'] = [item for item in zones if item['id'] != delete_zone_id]
            elif zone is not None:
                name = place_name(zone.get('name'))
                corners = zone_corners(zone.get('corners'))
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
                    'can_drive': bool(zone.get('can_drive')), 'corners': corners,
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

        self.declare_parameter('named_places_file', '~/.config/sverk-rover/named_places.json')
        self.declare_parameter('named_places_service', '/rover/named_places')
        self._places_store = NamedPlacesStore(self.get_parameter('named_places_file').value)
        self._places_instance = uuid.uuid4().hex
        self._places_map_cache = {}
        self._places_prepared = None
        self._places_runtime_map_id = None
        self._zone_inspection = {
            'id': None, 'state': 'idle',
            'message': 'Choose a no-drive zone to test its inspection route.',
            'zone_name': '', 'map': '', 'route': [], 'current_index': None,
            'qr_codes': [], 'started_at': None,
        }
        self._places_service = self.create_service(
            NamedPlaces, str(self.get_parameter('named_places_service').value), self._places_callback)

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
            if action in {'save_zone', 'delete_zone'}:
                self._assert_navigation_runtime_idle()
            if action == 'save':
                self._places_store.update(map_id, request.get('revision'), point=request.get('point', {}))
            elif action == 'delete':
                self._places_store.update(map_id, request.get('revision'), delete_id=request.get('id', ''))
            elif action == 'save_zone':
                self._places_store.update(map_id, request.get('revision'), zone=request.get('zone', {}))
            elif action == 'delete_zone':
                self._places_store.update(map_id, request.get('revision'), delete_zone_id=request.get('id', ''))
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
            pixels = []
            for corner in zone['corners']:
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
            point = next((p for p in points['places'] if p['name'].casefold() == name.casefold()), None)
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

    @staticmethod
    def _zone_inspection_route(corners, clearance_m, step_m):
        """Build clockwise inspection goals on a contour parallel to the zone."""
        corners = zone_corners(corners)
        clearance_m, step_m = float(clearance_m), float(step_m)
        if not 0.10 <= clearance_m <= 1.50:
            raise ValueError('Inspection clearance must be between 0.10 and 1.50 m')
        if not 0.10 <= step_m <= 1.00:
            raise ValueError('Inspection step must be between 0.10 and 1.00 m')
        signed_area = sum(corners[index]['x'] * corners[(index + 1) % 4]['y']
                          - corners[(index + 1) % 4]['x'] * corners[index]['y']
                          for index in range(4))
        lines = []
        for index, first in enumerate(corners):
            second = corners[(index + 1) % 4]
            dx, dy = second['x'] - first['x'], second['y'] - first['y']
            length = math.hypot(dx, dy)
            normal = (dy / length, -dx / length) if signed_area > 0 else (-dy / length, dx / length)
            lines.append(((first['x'] + normal[0] * clearance_m,
                           first['y'] + normal[1] * clearance_m), (dx, dy)))

        def intersection(previous, current):
            (ax, ay), (adx, ady) = previous
            (bx, by), (bdx, bdy) = current
            determinant = adx * bdy - ady * bdx
            if abs(determinant) < 1e-8:
                raise ValueError('Zone sides must not be parallel')
            factor = ((bx - ax) * bdy - (by - ay) * bdx) / determinant
            return {'x': ax + factor * adx, 'y': ay + factor * ady}

        contour = [intersection(lines[(index - 1) % 4], lines[index]) for index in range(4)]
        contour.reverse()  # Always follow the perimeter clockwise.
        center = {'x': sum(point['x'] for point in contour) / 4,
                  'y': sum(point['y'] for point in contour) / 4}
        route = []
        for index, first in enumerate(contour):
            second = contour[(index + 1) % 4]
            count = max(1, math.ceil(math.hypot(second['x'] - first['x'], second['y'] - first['y']) / step_m))
            for offset in range(count):
                ratio = offset / count
                x = first['x'] + (second['x'] - first['x']) * ratio
                y = first['y'] + (second['y'] - first['y']) * ratio
                route.append({'x': x, 'y': y, 'yaw': math.atan2(center['y'] - y, center['x'] - x)})
        return route

    def zone_inspection_payload(self):
        with self._lock:
            result = dict(self._zone_inspection)
            result['route'] = [dict(point) for point in result['route']]
            result['qr_codes'] = list(result['qr_codes'])
            return result

    def _set_zone_inspection(self, **changes):
        with self._lock:
            self._zone_inspection.update(changes)

    def _zone_inspection_qr_codes(self, after_count, timeout_sec=2.0):
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            payload = self.vision_qr_detections()
            if payload.get('message_count', 0) > after_count:
                result = payload.get('result') or {}
                codes = [str(item.get('data')).strip() for item in result.get('codes', [])
                         if isinstance(item, dict) and str(item.get('data', '')).strip()]
                if codes:
                    return codes
            time.sleep(0.15)
        return []

    def start_zone_inspection(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected an object')
        with self._navigation_control_lock:
            if self.zone_inspection_payload()['state'] in {'starting', 'active'}:
                raise RuntimeError('Zone inspection is already running')
            map_name = str(request.get('map') or '')
            payload = self.named_places_payload(map_name)
            zone = next((item for item in payload['zones'] if item['id'] == str(request.get('zone_id') or '')), None)
            if zone is None:
                raise ValueError('Choose a saved zone for inspection')
            if zone['can_drive']:
                raise ValueError('Inspection is available only for a no-drive zone')
            route = self._zone_inspection_route(zone['corners'], request.get('clearance_m', 0.30), request.get('step_m', 0.30))
            runtime = self.navigation_status_payload()
            if runtime['running']:
                if runtime['mode'] != 'navigation' or runtime['phase'] != 'running' or runtime['map'] != map_name:
                    raise RuntimeError('Nav2 must be running for the selected map')
                if not runtime.get('map_pose'):
                    raise RuntimeError('Current map pose is unavailable. Check localization before moving.')
                self.send_navigation_goal({'goal': route[0]})
            else:
                prepared = self._places_preparation()
                if prepared['map'] != map_name:
                    raise RuntimeError('Prepare the selected map and initial pose before inspection.')
                self.start_navigation({'map': map_name, 'initial_pose': prepared['initial_pose'], 'goal': route[0]})
                self._places_prepared = None
            inspection_id = uuid.uuid4().hex
            self._set_zone_inspection(id=inspection_id, state='starting',
                                      message='Starting Nav2 and moving to the inspection contour.',
                                      zone_name=zone['name'], map=map_name, route=route,
                                      current_index=0, qr_codes=[], started_at=time.time())
            threading.Thread(target=self._zone_inspection_worker, args=(inspection_id,), name='rover-zone-inspection', daemon=True).start()
            self.record_activity('navigation', 'Zone inspection started', {'zone': zone['name']})
            return self.zone_inspection_payload()

    def stop_zone_inspection(self):
        with self._navigation_control_lock:
            status = self.zone_inspection_payload()
            if status['state'] not in {'starting', 'active'}:
                raise RuntimeError('Zone inspection is not running')
            self._set_zone_inspection(state='canceled', message='Inspection canceled by the operator.')
            runtime = self.navigation_status_payload()
            if runtime['goal_state'] in {'queued', 'sending', 'active', 'canceling'}:
                self.cancel_navigation_goal()
            self.record_activity('navigation', 'Zone inspection canceled', {'zone': status['zone_name']})
            return self.zone_inspection_payload()

    def _zone_inspection_worker(self, inspection_id):
        index = 0
        while True:
            status = self.zone_inspection_payload()
            if status['id'] != inspection_id or status['state'] not in {'starting', 'active'}:
                return
            runtime = self.navigation_status_payload()
            goal_state = runtime.get('goal_state')
            if goal_state in {'queued', 'sending', 'active'}:
                self._set_zone_inspection(state='active', current_index=index,
                                          message=f'Inspecting point {index + 1}/{len(status["route"])}.')
                time.sleep(0.25)
                continue
            if goal_state != 'succeeded':
                self._set_zone_inspection(state='error', current_index=index,
                                          message=f'Inspection stopped: navigation goal is {goal_state}.')
                return
            before_count = self.vision_qr_detections().get('message_count', 0)
            codes = self._zone_inspection_qr_codes(before_count)
            if codes:
                combined = list(dict.fromkeys(status['qr_codes'] + codes))
                self._set_zone_inspection(state='succeeded', current_index=index, qr_codes=combined,
                                          message='QR code found. Inspection completed safely.')
                self.record_activity('vision', 'QR found during zone inspection', {'zone': status['zone_name'], 'codes': combined})
                return
            index += 1
            if index >= len(status['route']):
                self._set_zone_inspection(state='completed', current_index=len(status['route']) - 1,
                                          message='Full clockwise contour completed. QR code was not detected.')
                self.record_activity('navigation', 'Zone inspection completed', {'zone': status['zone_name']})
                return
            try:
                self.send_navigation_goal({'goal': status['route'][index]})
            except Exception as exc:
                self._set_zone_inspection(state='error', current_index=index,
                                          message=f'Could not send next inspection goal: {exc}')
                return
