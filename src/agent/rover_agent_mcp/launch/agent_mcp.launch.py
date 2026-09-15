from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_configuration import (
    config_path, environment_overrides, read_config, resolve_runtime_references,
)


def launch_setup(context):
    config = read_config(LaunchConfiguration('config_file').perform(context))
    mcp = environment_overrides(config['mcp_server'], {
        'mcp_host': ('MCP_HOST', str),
        'mcp_port': ('MCP_PORT', int),
        'cmd_vel_topic': ('ROVER_CMD_VEL_TOPIC', str),
        'led_set_state_service': ('ROVER_LED_SERVICE', str),
        'led_state_topic': ('ROVER_LED_STATE_TOPIC', str),
        'nav2_action_name': ('ROVER_NAV_ACTION', str),
        'odom_topic': ('ROVER_ODOM_TOPIC', str),
        'amcl_pose_topic': ('ROVER_AMCL_POSE_TOPIC', str),
        'scan_topic': ('ROVER_SCAN_TOPIC', str),
    })
    mcp = resolve_runtime_references(mcp)
    agent = resolve_runtime_references(config['text_agent'], {
        'mcp': {'url': f"http://127.0.0.1:{mcp['mcp_port']}/mcp"},
    })
    agent = environment_overrides(agent, {
        'robot_id': ('FLEET_ROBOT_ID', str),
        'mcp_url': ('MCP_URL', str),
        'text_command_topic': ('AGENT_TEXT_COMMAND_TOPIC', str),
        'status_topic': ('AGENT_STATUS_TOPIC', str),
        'answer_topic': ('AGENT_ANSWER_TOPIC', str),
        'prompt_file': ('AGENT_PROMPT_FILE', str),
        'llm_base_url': ('OPENAI_BASE_URL|OPENROUTER_BASE_URL|SVERK_BASE_URL', str),
        'llm_model': ('OPENAI_MODEL|OPENROUTER_MODEL|SVERK_MODEL', str),
        'llm_api_key_env': ('LLM_API_KEY_ENV', str),
        'native_tool_mode': ('LLM_NATIVE_TOOL_MODE', str),
        'timeout_s': ('LLM_TIMEOUT_SEC', float),
        'max_tool_rounds': ('LLM_MAX_TOOL_ROUNDS', int),
    })
    return [
        Node(package='rover_agent_mcp', executable='rover_mcp_server',
             name='rover_mcp_server', output='screen', parameters=[mcp]),
        Node(package='rover_agent_mcp', executable='agent_text_node',
             name='rover_agent_text_node', output='screen', parameters=[agent]),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=config_path('rover_agent_mcp', 'agent.yaml')),
        OpaqueFunction(function=launch_setup),
    ])
