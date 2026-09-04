from __future__ import annotations

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _launch_setup(context):
    share = Path(get_package_share_directory('fleet_text_bridge_ros2'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        config_file = str(share / 'config' / 'bridge.yaml')

    overrides = {}
    for name, value_type in (
        ('robot_id', str),
        ('mqtt_host', str),
        ('mqtt_port', int),
        ('mqtt_topic_prefix', str),
        ('mqtt_username', str),
        ('mqtt_password_env', str),
        ('command_topic', str),
        ('answer_topic', str),
        ('status_topic', str),
        ('duplicate_cache_size', int),
        ('agent_command_timeout_sec', float),
    ):
        raw = LaunchConfiguration(name).perform(context).strip()
        if raw:
            overrides[name] = value_type(raw)

    return [Node(
        package='fleet_text_bridge_ros2',
        executable='bridge_node',
        name='fleet_text_bridge',
        output='screen',
        parameters=[config_file, overrides],
    )]


def generate_launch_description():
    env = os.environ
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='bridge'),
        DeclareLaunchArgument('robot_id', default_value=env.get('FLEET_ROBOT_ID', '')),
        DeclareLaunchArgument('mqtt_host', default_value=env.get('FLEET_MQTT_HOST', env.get('FLEET_SERVER_IP', ''))),
        DeclareLaunchArgument('mqtt_port', default_value=env.get('FLEET_MQTT_PORT', '')),
        DeclareLaunchArgument('mqtt_topic_prefix', default_value=env.get('FLEET_MQTT_TOPIC_PREFIX', '')),
        DeclareLaunchArgument('mqtt_username', default_value=env.get('FLEET_MQTT_USERNAME', '')),
        DeclareLaunchArgument('mqtt_password_env', default_value=env.get('FLEET_MQTT_PASSWORD_ENV', '')),
        DeclareLaunchArgument('command_topic', default_value=env.get('AGENT_TEXT_COMMAND_TOPIC', '')),
        DeclareLaunchArgument('answer_topic', default_value=env.get('AGENT_ANSWER_TOPIC', '')),
        DeclareLaunchArgument('status_topic', default_value=env.get('AGENT_STATUS_TOPIC', '')),
        DeclareLaunchArgument('duplicate_cache_size', default_value=env.get('FLEET_DUPLICATE_CACHE_SIZE', '')),
        DeclareLaunchArgument('agent_command_timeout_sec', default_value=env.get('FLEET_AGENT_COMMAND_TIMEOUT_SEC', '')),
        OpaqueFunction(function=_launch_setup),
    ])
