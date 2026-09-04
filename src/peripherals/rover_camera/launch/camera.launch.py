from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _launch_setup(context):
    share = Path(get_package_share_directory('rover_camera'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        variant = LaunchConfiguration('variant').perform(context).strip() or 'camera'
        config_file = str(share / 'config' / f'{variant}.yaml')

    types = {
        'device': str,
        'image_topic': str,
        'compressed_image_topic': str,
        'frame_id': str,
        'rotate': int,
    }
    overrides = {
        'use_sim_time': LaunchConfiguration('use_sim_time').perform(context).lower()
        in {'1', 'true', 'yes', 'on'},
    }
    for name, value_type in types.items():
        raw = LaunchConfiguration(name).perform(context).strip()
        if raw:
            overrides[name] = value_type(raw)

    return [Node(
        package='rover_camera',
        executable='usb_camera_node',
        name='usb_camera_node',
        output='screen',
        additional_env={'PYTHONNOUSERSITE': '1'},
        parameters=[config_file, overrides],
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='camera'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('device', default_value=''),
        DeclareLaunchArgument('image_topic', default_value=''),
        DeclareLaunchArgument('compressed_image_topic', default_value=''),
        DeclareLaunchArgument('frame_id', default_value=''),
        DeclareLaunchArgument('rotate', default_value=''),
        OpaqueFunction(function=_launch_setup),
    ])
