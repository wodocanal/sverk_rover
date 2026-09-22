from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_configuration import (
    config_path, environment_overrides, read_config, resolve_runtime_references,
)


def launch_setup(context):
    config = read_config(LaunchConfiguration('config_file').perform(context))
    parameters = resolve_runtime_references(config['fleet_bridge'])
    parameters = environment_overrides(parameters, {
        'robot_id': ('FLEET_ROBOT_ID', str),
        'mqtt_host': ('FLEET_MQTT_HOST|FLEET_SERVER_IP', str),
        'mqtt_port': ('FLEET_MQTT_PORT', int),
        'mqtt_topic_prefix': ('FLEET_MQTT_TOPIC_PREFIX', str),
        'mqtt_username': ('FLEET_MQTT_USERNAME', str),
        'mqtt_password_env': ('FLEET_MQTT_PASSWORD_ENV', str),
        'command_topic': ('AGENT_TEXT_COMMAND_TOPIC', str),
        'answer_topic': ('AGENT_ANSWER_TOPIC', str),
        'status_topic': ('AGENT_STATUS_TOPIC', str),
        'duplicate_cache_size': ('FLEET_DUPLICATE_CACHE_SIZE', int),
        'agent_command_timeout_sec': ('FLEET_AGENT_COMMAND_TIMEOUT_SEC', float),
    })
    return [Node(
        package='fleet_text_bridge_ros2', executable='bridge_node',
        name='fleet_text_bridge', output='screen', parameters=[parameters],
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=config_path('fleet_text_bridge_ros2', 'bridge.yaml')),
        OpaqueFunction(function=launch_setup),
    ])
