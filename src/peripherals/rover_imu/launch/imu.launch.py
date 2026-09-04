from __future__ import annotations

from ast import literal_eval
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _launch_setup(context):
    share = Path(get_package_share_directory('rover_imu'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        variant = LaunchConfiguration('variant').perform(context).strip()
        config_file = str(share / 'config' / f'{variant or "yb_mra02_v1"}.yaml')

    types = {
        'serial_device': str,
        'baudrate': int,
        'frame_id': str,
        'imu_topic': str,
        'mag_topic': str,
        'euler_topic': str,
        'frame_count_topic': str,
    }
    overrides = {
        'use_sim_time': LaunchConfiguration('use_sim_time').perform(context).lower()
        in {'1', 'true', 'yes', 'on'},
    }
    for name, value_type in types.items():
        raw = LaunchConfiguration(name).perform(context).strip()
        if raw:
            overrides[name] = value_type(raw)
    for name in ('axis_map', 'axis_signs'):
        raw = LaunchConfiguration(name).perform(context).strip()
        if raw:
            value = literal_eval(raw)
            if not isinstance(value, list):
                raise ValueError(f'{name} must be a list')
            overrides[name] = value

    return [Node(
        package='rover_imu',
        executable='yahboom_imu_node',
        name='yahboom_imu_node',
        output='screen',
        parameters=[config_file, overrides],
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='yb_mra02_v1'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('serial_device', default_value=''),
        DeclareLaunchArgument('baudrate', default_value=''),
        DeclareLaunchArgument('frame_id', default_value=''),
        DeclareLaunchArgument('imu_topic', default_value=''),
        DeclareLaunchArgument('mag_topic', default_value=''),
        DeclareLaunchArgument('euler_topic', default_value=''),
        DeclareLaunchArgument('frame_count_topic', default_value=''),
        DeclareLaunchArgument('axis_map', default_value=''),
        DeclareLaunchArgument('axis_signs', default_value=''),
        OpaqueFunction(function=_launch_setup),
    ])
