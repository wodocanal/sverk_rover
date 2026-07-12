import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    mcp_host = LaunchConfiguration('mcp_host')
    mcp_port = LaunchConfiguration('mcp_port')
    mcp_url = LaunchConfiguration('mcp_url')

    # Generic LLM parameters. openrouter_* aliases are kept for compatibility.
    llm_base_url = LaunchConfiguration('llm_base_url')
    llm_model = LaunchConfiguration('llm_model')
    llm_api_key_env = LaunchConfiguration('llm_api_key_env')
    native_tool_mode = LaunchConfiguration('native_tool_mode')
    openrouter_base_url = LaunchConfiguration('openrouter_base_url')
    openrouter_model = LaunchConfiguration('openrouter_model')
    openrouter_api_key_env = LaunchConfiguration('openrouter_api_key_env')

    text_command_topic = LaunchConfiguration('text_command_topic')
    status_topic = LaunchConfiguration('status_topic')
    answer_topic = LaunchConfiguration('answer_topic')
    prompt_file = LaunchConfiguration('prompt_file')

    cmd_vel_topic = LaunchConfiguration('cmd_vel_topic')
    led_service = LaunchConfiguration('led_service')
    scan_front_angle_deg = LaunchConfiguration('scan_front_angle_deg')
    use_sim_time = LaunchConfiguration('use_sim_time')

    motion_default_speed_mps = LaunchConfiguration('motion_default_speed_mps')
    motion_default_lateral_speed_mps = LaunchConfiguration('motion_default_lateral_speed_mps')
    motion_default_angular_speed_degps = LaunchConfiguration('motion_default_angular_speed_degps')
    motion_position_tolerance_m = LaunchConfiguration('motion_position_tolerance_m')
    motion_yaw_tolerance_deg = LaunchConfiguration('motion_yaw_tolerance_deg')

    default_prompt_file = PathJoinSubstitution([
        FindPackageShare('rover_agent_mcp'),
        'config',
        'default_system_prompt.md',
    ])

    return LaunchDescription([
        DeclareLaunchArgument('mcp_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('mcp_port', default_value='8765'),
        DeclareLaunchArgument('mcp_url', default_value='http://127.0.0.1:8765/mcp'),

        DeclareLaunchArgument('llm_base_url', default_value=os.getenv('OPENAI_BASE_URL', '')),
        DeclareLaunchArgument('llm_model', default_value=os.getenv('OPENAI_MODEL', '')),
        DeclareLaunchArgument('llm_api_key_env', default_value='OPENAI_API_KEY'),
        DeclareLaunchArgument('native_tool_mode', default_value='auto'),  # auto, true, false

        DeclareLaunchArgument('openrouter_base_url', default_value=os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')),
        DeclareLaunchArgument('openrouter_model', default_value=os.getenv('OPENROUTER_MODEL', '')),
        DeclareLaunchArgument('openrouter_api_key_env', default_value='OPENROUTER_API_KEY'),

        DeclareLaunchArgument('text_command_topic', default_value='/agent/text_command'),
        DeclareLaunchArgument('status_topic', default_value='/agent/status'),
        DeclareLaunchArgument('answer_topic', default_value='/agent/answer'),
        DeclareLaunchArgument('prompt_file', default_value=default_prompt_file),

        DeclareLaunchArgument('cmd_vel_topic', default_value='/cmd_vel_test'),
        DeclareLaunchArgument('led_service', default_value='/led_strip/set_state'),
        DeclareLaunchArgument('scan_front_angle_deg', default_value='0.0'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),

        DeclareLaunchArgument('motion_default_speed_mps', default_value='0.12'),
        DeclareLaunchArgument('motion_default_lateral_speed_mps', default_value='0.10'),
        DeclareLaunchArgument('motion_default_angular_speed_degps', default_value='45.0'),
        DeclareLaunchArgument('motion_position_tolerance_m', default_value='0.025'),
        DeclareLaunchArgument('motion_yaw_tolerance_deg', default_value='3.0'),

        Node(
            package='rover_agent_mcp',
            executable='rover_mcp_server',
            name='rover_mcp_server',
            output='screen',
            parameters=[{
                'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
                'mcp_host': mcp_host,
                'mcp_port': ParameterValue(mcp_port, value_type=int),
                'cmd_vel_topic': cmd_vel_topic,
                'led_set_state_service': led_service,
                'scan_front_angle_deg': ParameterValue(scan_front_angle_deg, value_type=float),
                'default_forward_speed_mps': ParameterValue(motion_default_speed_mps, value_type=float),
                'default_lateral_speed_mps': ParameterValue(motion_default_lateral_speed_mps, value_type=float),
                'default_angular_speed_degps': ParameterValue(motion_default_angular_speed_degps, value_type=float),
                'motion_position_tolerance_m': ParameterValue(motion_position_tolerance_m, value_type=float),
                'motion_yaw_tolerance_deg': ParameterValue(motion_yaw_tolerance_deg, value_type=float),
            }],
        ),
        Node(
            package='rover_agent_mcp',
            executable='agent_text_node',
            name='rover_agent_text_node',
            output='screen',
            parameters=[{
                'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
                'mcp_url': ParameterValue(mcp_url, value_type=str),
                'text_command_topic': ParameterValue(text_command_topic, value_type=str),
                'status_topic': ParameterValue(status_topic, value_type=str),
                'answer_topic': ParameterValue(answer_topic, value_type=str),
                'prompt_file': ParameterValue(prompt_file, value_type=str),
                'llm_base_url': ParameterValue(llm_base_url, value_type=str),
                'llm_model': ParameterValue(llm_model, value_type=str),
                'llm_api_key_env': ParameterValue(llm_api_key_env, value_type=str),
                'native_tool_mode': ParameterValue(native_tool_mode, value_type=str),
                'openrouter_base_url': ParameterValue(openrouter_base_url, value_type=str),
                'openrouter_model': ParameterValue(openrouter_model, value_type=str),
                'openrouter_api_key_env': ParameterValue(openrouter_api_key_env, value_type=str),
            }],
        ),
    ])
