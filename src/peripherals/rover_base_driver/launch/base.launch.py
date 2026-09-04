from __future__ import annotations

from ast import literal_eval
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
    if value_type is list:
        value = literal_eval(raw)
        if not isinstance(value, list):
            raise ValueError(f'{name} must be a list')
        return value
    return value_type(raw)


def _launch_setup(context):
    share = Path(get_package_share_directory('rover_base_driver'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        variant = LaunchConfiguration('variant').perform(context).strip() or 'base'
        config_file = str(share / 'config' / f'{variant}.yaml')

    fields = {
        'serial_device': str,
        'baudrate': int,
        'cmd_vel_topic': str,
        'wheel_radius_m': float,
        'wheelbase_m': float,
        'track_width_m': float,
        'encoder_lines': float,
        'reduction_ratio': float,
        'quadrature_factor': float,
        'motor_command_order': list,
        'motor_command_signs': list,
        'encoder_feedback_order': list,
        'encoder_feedback_signs': list,
    }
    overrides = {'use_sim_time': _optional(context, 'use_sim_time', bool)}
    for name, value_type in fields.items():
        value = _optional(context, name, value_type)
        if value is not None:
            overrides[name] = value

    return [Node(
        package='rover_base_driver',
        executable='base_driver_node',
        name='base_driver_node',
        output='screen',
        parameters=[config_file, overrides],
    )]


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='base'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
    ]
    for name in (
        'serial_device', 'baudrate', 'cmd_vel_topic', 'wheel_radius_m',
        'wheelbase_m', 'track_width_m', 'encoder_lines', 'reduction_ratio',
        'quadrature_factor', 'motor_command_order', 'motor_command_signs',
        'encoder_feedback_order', 'encoder_feedback_signs',
    ):
        arguments.append(DeclareLaunchArgument(name, default_value=''))
    return LaunchDescription([*arguments, OpaqueFunction(function=_launch_setup)])
