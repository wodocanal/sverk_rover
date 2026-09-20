import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from rover_web import web_gateway_node as module
from rover_web.web_gateway_node import RoverWebGateway


def library(root):
    gateway = SimpleNamespace(maps_root=root)
    for name in ['_map_library_roots', '_map_library_location', '_resolve_map_yaml',
                 '_resolve_map_image', '_map_metadata_payload', 'maps_payload', 'map_image']:
        setattr(gateway, name, getattr(RoverWebGateway, name).__get__(gateway))
    gateway._map_origin = RoverWebGateway._map_origin
    return gateway


def write_map(directory, label=None):
    directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(directory/'map.pgm'), np.full((12, 16), 254, dtype=np.uint8))
    (directory/'map.yaml').write_text('image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n')
    if label:
        (directory/'map_info.json').write_text(json.dumps({'label':label,'created_at':'2026-09-20T12:00:00+03:00'}))


def test_current_and_archived_maps_list_preview_and_read_only_selection(tmp_path):
    root = tmp_path/'maps/current'
    write_map(root, 'current-room')
    old = tmp_path/'maps/archive/old_version'
    write_map(old, 'old-room')
    write_map(tmp_path/'maps/archive/legacy')
    write_map(tmp_path/'maps/.staging_ignored')
    gateway = library(root)
    before = (root/'map.yaml').read_bytes()
    entries = gateway.maps_payload()['maps']
    assert len(entries) == 3
    assert entries[0]['path'] == 'map.yaml'
    archived = next(item for item in entries if item['path'] == 'archive/old_version/map.yaml')
    assert archived['name'] == 'old-room' and archived['archived']
    assert archived['created_at'] and archived['revision']
    assert gateway._resolve_map_yaml(archived['path']) == old/'map.yaml'
    image, mime = gateway.map_image(archived['path'])
    assert image.startswith(b'\x89PNG') and mime == 'image/png'
    assert (root/'map.yaml').read_bytes() == before


def test_archive_visible_without_current_and_broken_map_is_reported(tmp_path):
    root = tmp_path/'maps/current'
    write_map(tmp_path/'maps/archive/old')
    broken = tmp_path/'maps/archive/broken'
    broken.mkdir()
    (broken/'map.yaml').write_text('image: missing.pgm\n')
    entries = library(root).maps_payload()['maps']
    assert len(entries) == 2
    assert next(item for item in entries if item['path'].endswith('old/map.yaml'))['valid']
    assert not next(item for item in entries if 'broken/' in item['path'])['valid']


def test_archive_path_and_image_traversal_are_rejected(tmp_path):
    root = tmp_path/'maps/current'
    write_map(root)
    write_map(tmp_path/'outside')
    old = tmp_path/'maps/archive/old'
    write_map(old)
    gateway = library(root)
    for path in ['../archive/old/map.yaml', 'archive/../../../outside/map.yaml']:
        with pytest.raises(PermissionError):
            gateway._resolve_map_yaml(path)
    (old/'escape.yaml').symlink_to(tmp_path/'outside/map.yaml')
    with pytest.raises(PermissionError):
        gateway._resolve_map_yaml('archive/old/escape.yaml')
    with pytest.raises(PermissionError):
        gateway._resolve_map_image(old/'map.yaml', {'image':str(tmp_path/'outside/map.pgm')})


def test_navigation_receives_archive_yaml_without_activating_map(tmp_path, monkeypatch):
    root = tmp_path/'maps/current'
    old = tmp_path/'maps/archive/old'
    write_map(old)
    gateway = library(root)
    gateway._navigation_control_lock = threading.RLock()
    gateway._lock = threading.RLock()
    gateway._motor_calibration_active = False
    gateway._assert_navigation_runtime_idle = Mock()
    gateway._assert_navigation_topics = Mock()
    gateway._navigation_pose = RoverWebGateway._navigation_pose
    gateway.navigation_package = 'rover_navigation'
    gateway.navigation_settings_file = str(tmp_path/'navigation.yaml')
    gateway.drive_type_file = str(tmp_path/'drive_type')
    gateway.navigation_launch_file = 'navigation.launch.py'
    gateway._start_navigation_process = Mock()
    gateway._navigation_generation = 1
    gateway._initialize_navigation = Mock()
    gateway.navigation_status_payload = Mock(return_value={})
    monkeypatch.setattr(module.threading, 'Thread', Mock())
    RoverWebGateway.start_navigation(gateway, {'map':'archive/old/map.yaml',
        'initial_pose':{'x':0,'y':0,'yaw':0}, 'goal':{'x':1,'y':1,'yaw':0}})
    command = gateway._start_navigation_process.call_args.args[1]
    assert f'map:={old}/map.yaml' in command
    assert not root.exists()
