from __future__ import annotations

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _bool(value: str) -> bool:
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _optional(context, name: str, value_type=str):
    value = LaunchConfiguration(name).perform(context).strip()
    return value_type(value) if value else None


def _launch_setup(context):
    share = Path(get_package_share_directory('rover_agent_mcp'))
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file:
        config_file = str(share / 'config' / 'agent.yaml')

    common_topics = {
        'robot_id': str,
        'text_command_topic': str,
        'status_topic': str,
        'answer_topic': str,
    }
    text_overrides = {}
    for name, value_type in (
        *common_topics.items(),
        ('mcp_url', str),
        ('prompt_file', str),
        ('llm_base_url', str),
        ('llm_model', str),
        ('llm_api_key_env', str),
        ('native_tool_mode', str),
        ('timeout_s', float),
        ('max_tool_rounds', int),
    ):
        value = _optional(context, name, value_type)
        if value is not None:
            text_overrides[name] = value
    if 'prompt_file' not in text_overrides:
        text_overrides['prompt_file'] = str(share / 'config' / 'default_system_prompt.md')

    mcp_overrides = {}
    for name, value_type in (
        ('mcp_host', str),
        ('mcp_port', int),
        ('cmd_vel_topic', str),
        ('led_set_state_service', str),
        ('led_state_topic', str),
        ('nav2_action_name', str),
        ('odom_topic', str),
        ('amcl_pose_topic', str),
        ('scan_topic', str),
    ):
        value = _optional(context, name, value_type)
        if value is not None:
            mcp_overrides[name] = value
    if 'mcp_url' not in text_overrides and 'mcp_port' in mcp_overrides:
        text_overrides['mcp_url'] = (
            f"http://127.0.0.1:{mcp_overrides['mcp_port']}/mcp"
        )

    actions = []
    if _bool(LaunchConfiguration('use_mcp_server').perform(context)):
        actions.append(Node(
            package='rover_agent_mcp',
            executable='rover_mcp_server',
            name='rover_mcp_server',
            output='screen',
            parameters=[config_file, mcp_overrides],
        ))
    if _bool(LaunchConfiguration('use_text_agent').perform(context)):
        actions.append(Node(
            package='rover_agent_mcp',
            executable='agent_text_node',
            name='rover_agent_text_node',
            output='screen',
            parameters=[config_file, text_overrides],
        ))
    return actions


def generate_launch_description():
    env = os.environ
    arguments = [
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('variant', default_value='agent'),
        DeclareLaunchArgument('use_mcp_server', default_value='true'),
        DeclareLaunchArgument('use_text_agent', default_value='true'),
        DeclareLaunchArgument('robot_id', default_value=env.get('FLEET_ROBOT_ID', '')),
        DeclareLaunchArgument('mcp_host', default_value=env.get('MCP_HOST', '')),
        DeclareLaunchArgument('mcp_port', default_value=env.get('MCP_PORT', '')),
        DeclareLaunchArgument('mcp_url', default_value=env.get('MCP_URL', '')),
        DeclareLaunchArgument('cmd_vel_topic', default_value=env.get('ROVER_CMD_VEL_TOPIC', '')),
        DeclareLaunchArgument('led_set_state_service', default_value=env.get('ROVER_LED_SERVICE', '')),
        DeclareLaunchArgument('led_state_topic', default_value=env.get('ROVER_LED_STATE_TOPIC', '')),
        DeclareLaunchArgument('nav2_action_name', default_value=env.get('ROVER_NAV_ACTION', '')),
        DeclareLaunchArgument('odom_topic', default_value=env.get('ROVER_ODOM_TOPIC', '')),
        DeclareLaunchArgument('amcl_pose_topic', default_value=env.get('ROVER_AMCL_POSE_TOPIC', '')),
        DeclareLaunchArgument('scan_topic', default_value=env.get('ROVER_SCAN_TOPIC', '')),
        DeclareLaunchArgument('text_command_topic', default_value=env.get('AGENT_TEXT_COMMAND_TOPIC', '')),
        DeclareLaunchArgument('status_topic', default_value=env.get('AGENT_STATUS_TOPIC', '')),
        DeclareLaunchArgument('answer_topic', default_value=env.get('AGENT_ANSWER_TOPIC', '')),
        DeclareLaunchArgument('prompt_file', default_value=env.get('AGENT_PROMPT_FILE', '')),
        DeclareLaunchArgument('llm_base_url', default_value=env.get('OPENAI_BASE_URL', '')),
        DeclareLaunchArgument('llm_model', default_value=env.get('OPENAI_MODEL', '')),
        DeclareLaunchArgument('llm_api_key_env', default_value=env.get('LLM_API_KEY_ENV', '')),
        DeclareLaunchArgument('native_tool_mode', default_value=env.get('LLM_NATIVE_TOOL_MODE', '')),
        DeclareLaunchArgument('timeout_s', default_value=env.get('LLM_TIMEOUT_SEC', '')),
        DeclareLaunchArgument('max_tool_rounds', default_value=env.get('LLM_MAX_TOOL_ROUNDS', '')),
    ]
    return LaunchDescription([*arguments, OpaqueFunction(function=_launch_setup)])
