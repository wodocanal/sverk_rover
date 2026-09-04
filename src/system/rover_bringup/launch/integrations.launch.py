from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from rover_bringup.configuration import (
    bringup_config_path,
    component_enabled,
    implementation,
    load_implementations,
    load_layer_profile,
    override_bool,
    read_yaml_file,
)


def _flag(context, profile: dict, name: str) -> bool:
    configured = component_enabled(profile, name, False)
    return override_bool(LaunchConfiguration(f'use_{name}').perform(context), configured)


def _add_if_set(arguments: dict[str, str], name: str, value) -> None:
    if value is not None and str(value).strip():
        arguments[name] = str(value)


def _include(implementations: dict, name: str, arguments: dict[str, str]):
    selected = implementation(implementations, 'integrations', name)
    source = (
        Path(get_package_share_directory(selected['package']))
        / 'launch'
        / selected['launch']
    )
    launch_arguments = dict(arguments)
    _add_if_set(launch_arguments, 'variant', selected['variant'])
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(source)),
        launch_arguments=launch_arguments.items(),
    )


def _launch_setup(context):
    profile_name = LaunchConfiguration('profile').perform(context).strip() or 'full'
    profile = load_layer_profile(
        'integrations',
        profile_name,
        LaunchConfiguration('profile_file').perform(context),
    )
    implementations = load_implementations(
        LaunchConfiguration('implementations_file').perform(context)
    )
    robot = dict(read_yaml_file(
        LaunchConfiguration('robot_config_file').perform(context)
    ).get('robot', {}))
    topics = dict(read_yaml_file(
        LaunchConfiguration('topics_config_file').perform(context)
    ).get('topics', {}))
    robot_id = str(robot.get('id', 'rover-01'))
    use_agent = _flag(context, profile, 'agent')
    use_fleet_bridge = _flag(context, profile, 'fleet_bridge')
    actions = [LogInfo(msg=f'Integrations profile={profile_name}; robot_id={robot_id}')]

    if use_agent:
        args = {
            'robot_id': robot_id,
            'cmd_vel_topic': topics.get('cmd_vel_test', '/cmd_vel_test'),
            'led_set_state_service': topics.get('led_set_state', '/led_strip/set_state'),
            'led_state_topic': topics.get('led_state', '/led_strip/state'),
            'odom_topic': topics.get('odom', '/odom'),
            'amcl_pose_topic': topics.get('amcl_pose', '/amcl_pose'),
            'scan_topic': topics.get('scan', '/scan_filtered'),
            'text_command_topic': topics.get('agent_text_command', '/agent/text_command'),
            'status_topic': topics.get('agent_status', '/agent/status'),
            'answer_topic': topics.get('agent_answer', '/agent/answer'),
        }
        for name in (
            'agent_config_file', 'mcp_host', 'mcp_port', 'mcp_url',
            'prompt_file', 'llm_base_url', 'llm_model', 'llm_api_key_env',
            'native_tool_mode', 'timeout_s', 'max_tool_rounds',
        ):
            target = 'config_file' if name == 'agent_config_file' else name
            _add_if_set(args, target, LaunchConfiguration(name).perform(context))
        actions.append(_include(implementations, 'agent', args))

    if use_fleet_bridge:
        args = {
            'robot_id': robot_id,
            'command_topic': topics.get('agent_text_command', '/agent/text_command'),
            'answer_topic': topics.get('agent_answer', '/agent/answer'),
            'status_topic': topics.get('agent_status', '/agent/status'),
        }
        for name in (
            'bridge_config_file', 'mqtt_host', 'mqtt_port', 'mqtt_topic_prefix',
            'mqtt_username', 'mqtt_password_env', 'duplicate_cache_size',
            'agent_command_timeout_sec',
        ):
            target = 'config_file' if name == 'bridge_config_file' else name
            _add_if_set(args, target, LaunchConfiguration(name).perform(context))
        actions.append(_include(implementations, 'fleet_bridge', args))
    return actions


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('profile', default_value='full'),
        DeclareLaunchArgument('profile_file', default_value=''),
        DeclareLaunchArgument('implementations_file', default_value=bringup_config_path('implementations.yaml')),
        DeclareLaunchArgument('robot_config_file', default_value=bringup_config_path('rover_v1.yaml')),
        DeclareLaunchArgument('topics_config_file', default_value=bringup_config_path('topics.yaml')),
        DeclareLaunchArgument('use_agent', default_value=''),
        DeclareLaunchArgument('use_fleet_bridge', default_value=''),
    ]
    for name in (
        'agent_config_file', 'bridge_config_file', 'mcp_host', 'mcp_port',
        'mcp_url', 'prompt_file', 'llm_base_url', 'llm_model',
        'llm_api_key_env', 'native_tool_mode', 'timeout_s', 'max_tool_rounds',
        'mqtt_host', 'mqtt_port', 'mqtt_topic_prefix', 'mqtt_username',
        'mqtt_password_env', 'duplicate_cache_size', 'agent_command_timeout_sec',
    ):
        arguments.append(DeclareLaunchArgument(name, default_value=''))
    return LaunchDescription([*arguments, OpaqueFunction(function=_launch_setup)])
