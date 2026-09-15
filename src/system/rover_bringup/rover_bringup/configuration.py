from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any

from ament_index_python.packages import get_package_share_directory
from rover_configuration import config_path, read_config


# This registry contains ownership and schema, never parameter values.
COMPONENT_CONFIGS = {
    'base': ('rover_base_driver', 'base.yaml', 'base_driver_node', 'base_driver'),
    'odometry': ('rover_wheel_odometry', 'odometry.yaml', 'wheel_odometry_node', 'wheel_odometry'),
    'imu': ('rover_imu', 'imu.yaml', 'yahboom_imu_node', 'imu'),
    'lidar': ('sllidar_ros2', 'lidar.yaml', 'sllidar_node', 'lidar'),
    'lidar_filter': ('rover_lidar_filter', 'default.yaml', 'lidar_footprint_filter', 'lidar_filter'),
    'camera': ('rover_camera', 'camera.yaml', 'usb_camera_node', 'camera'),
    'vision': ('rover_vision', 'vision.yaml', 'camera_detector_node', 'vision'),
    'led_strip': ('rover_led_strip', 'led_strip.yaml', 'led_strip_node', 'led_strip'),
    'octoliner': ('rover_octoliner', 'octoliner.yaml', 'octoliner_node', 'octoliner'),
    'audio': ('rover_waveshare_audio', 'audio.yaml', 'waveshare_audio_node', 'waveshare_audio'),
    'device_manager': ('rover_device_manager', 'device_manager.yaml', '', ''),
    'agent': ('rover_agent_mcp', 'agent.yaml', '', ''),
    'fleet_bridge': ('fleet_text_bridge_ros2', 'bridge.yaml', '', ''),
}


def bringup_share() -> Path:
    return Path(get_package_share_directory('rover_bringup'))


def bringup_config_path(*parts: str) -> str:
    return str(bringup_share().joinpath('config', *parts))


def read_yaml_file(path: str | Path) -> dict[str, Any]:
    return read_config(path)


def deep_merge(*sources: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in sources:
        result = _merge_two(result, source)
    return result


def resolve_references(value: Any, sources: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_references(item, sources) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_references(item, sources) for item in value]
    if isinstance(value, str) and value.startswith('@'):
        return _resolve_reference(value[1:], sources)
    return value


def _resolve_reference(reference: str, sources: dict[str, Any]) -> Any:
    if reference.startswith('env.'):
        return os.getenv(reference.removeprefix('env.'), '')

    current: Any = sources
    for part in reference.split('.'):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f'Unknown config reference: @{reference}')
        current = current[part]
    return current


def _merge_two(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_two(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def as_launch_bool(value: bool) -> str:
    return 'true' if value else 'false'


def component_enabled(
    profile_config: dict[str, Any],
    name: str,
    default: bool = False,
) -> bool:
    components = profile_config.get('components', {})
    if isinstance(components, dict) and name in components:
        return as_bool(components[name])
    return default


def override_bool(raw: str, current: bool) -> bool:
    text = raw.strip()
    return as_bool(text) if text else current


def load_profile(profile: str, profile_file: str = '') -> dict[str, Any]:
    path = Path(profile_file).expanduser() if profile_file.strip() else None
    if path is None:
        path = Path(bringup_config_path('profiles', f'{profile}.yaml'))
    return read_yaml_file(path)


def load_component(components_dir: str, name: str) -> dict[str, Any]:
    # Old external component directories remain an explicit opt-in override.
    if components_dir.strip():
        legacy_name = 'base' if name == 'odometry' else name
        if name == 'fleet_bridge':
            legacy_name = 'agent'
        return read_yaml_file(Path(components_dir).expanduser() / f'{legacy_name}.yaml')
    package, filename, node, section = COMPONENT_CONFIGS[name]
    config = read_yaml_file(config_path(package, filename))
    if not node:
        return config
    parameters = dict(config[node]['ros__parameters'])
    if name == 'lidar':
        parameters.update(config.get('discovery', {}))
    return {section: parameters}


def set_if_missing(target: dict[str, Any], key: str, value: Any) -> None:
    if key not in target or target[key] in ('', None):
        target[key] = value
