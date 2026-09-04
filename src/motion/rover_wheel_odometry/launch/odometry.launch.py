from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _optional(context, name: str, value_type):
    raw = LaunchConfiguration(name).perform(context).strip()
    if not raw:
        return None
    if value_type is bool:
        return raw.lower() in {'1', 'true', 'yes', 'on'}
    return value_type(raw)


def _launch_setup(context):
    share = Path(get_package_share_directory('rover_wheel_odometry'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        config_file = str(share / 'config' / 'odometry.yaml')

    fields = {
        'encoder_topic': str,
        'odometry_topic': str,
        'odom_frame_id': str,
        'base_frame_id': str,
        'wheel_radius_m': float,
        'wheelbase_m': float,
        'track_width_m': float,
        'encoder_lines': float,
        'reduction_ratio': float,
        'quadrature_factor': float,
        'x_multiplier': float,
        'y_multiplier': float,
        'yaw_multiplier': float,
    }
    overrides = {'use_sim_time': _optional(context, 'use_sim_time', bool)}
    for name, value_type in fields.items():
        value = _optional(context, name, value_type)
        if value is not None:
            overrides[name] = value

    return [Node(
        package='rover_wheel_odometry',
        executable='wheel_odometry_node',
        name='wheel_odometry_node',
        output='screen',
        parameters=[config_file, overrides],
    )]


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='odometry'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
    ]
    for name in (
        'encoder_topic', 'odometry_topic', 'odom_frame_id', 'base_frame_id',
        'wheel_radius_m', 'wheelbase_m', 'track_width_m', 'encoder_lines',
        'reduction_ratio', 'quadrature_factor', 'x_multiplier', 'y_multiplier',
        'yaw_multiplier',
    ):
        arguments.append(DeclareLaunchArgument(name, default_value=''))
    return LaunchDescription([*arguments, OpaqueFunction(function=_launch_setup)])
