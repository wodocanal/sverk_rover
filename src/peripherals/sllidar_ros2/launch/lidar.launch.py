from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _launch_setup(context):
    share = Path(get_package_share_directory('sllidar_ros2'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        variant = LaunchConfiguration('variant').perform(context).strip() or 'c1'
        config_file = str(share / 'config' / f'{variant}.yaml')

    types = {
        'serial_port': str,
        'serial_baudrate': int,
        'frame_id': str,
        'scan_mode': str,
        'scan_frequency': float,
        'range_min': float,
    }
    overrides = {
        'use_sim_time': LaunchConfiguration('use_sim_time').perform(context).lower()
        in {'1', 'true', 'yes', 'on'},
    }
    for name, value_type in types.items():
        raw = LaunchConfiguration(name).perform(context).strip()
        if raw:
            overrides[name] = value_type(raw)
    for name in ('inverted', 'angle_compensate'):
        raw = LaunchConfiguration(name).perform(context).strip()
        if raw:
            overrides[name] = raw.lower() in {'1', 'true', 'yes', 'on'}

    return [Node(
        package='sllidar_ros2',
        executable='sllidar_node',
        name='sllidar_node',
        output='screen',
        parameters=[config_file, overrides],
        remappings=[('scan', LaunchConfiguration('scan_topic').perform(context))],
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='c1'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('serial_port', default_value=''),
        DeclareLaunchArgument('serial_baudrate', default_value=''),
        DeclareLaunchArgument('frame_id', default_value=''),
        DeclareLaunchArgument('inverted', default_value=''),
        DeclareLaunchArgument('angle_compensate', default_value=''),
        DeclareLaunchArgument('scan_mode', default_value=''),
        DeclareLaunchArgument('scan_frequency', default_value=''),
        DeclareLaunchArgument('range_min', default_value=''),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        OpaqueFunction(function=_launch_setup),
    ])
