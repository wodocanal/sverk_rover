from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import FindExecutable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def default_rover_config_file() -> str:
    try:
        return str(
            Path(get_package_share_directory('rover_bringup'))
            / 'config'
            / 'rover.yaml'
        )
    except Exception:
        return ''


def default_workspace_root(web_share: Path) -> str:
    try:
        return str(web_share.parents[3])
    except Exception:
        return str(Path.home() / 'sverk_rover')


def generate_launch_description():
    web_share = Path(get_package_share_directory('rover_web'))
    terminal_shell = str(web_share / 'tools' / 'rover_terminal_shell.sh')

    return LaunchDescription([
        DeclareLaunchArgument('bind_address', default_value='0.0.0.0'),
        DeclareLaunchArgument('port', default_value='8765'),
        DeclareLaunchArgument('command_topic', default_value='/cmd_vel'),
        DeclareLaunchArgument(
            'rover_config_file',
            default_value=default_rover_config_file(),
        ),
        DeclareLaunchArgument(
            'plans_directory',
            default_value=str(
                Path.home() / '.local' / 'share' / 'sverh-rover-web' / 'plans'
            ),
        ),
        DeclareLaunchArgument(
            'hackathon_files_root',
            default_value=str(
                Path(default_workspace_root(web_share)) / 'hackathon_files'
            ),
        ),
        DeclareLaunchArgument('terminal_enabled', default_value='true'),
        DeclareLaunchArgument('start_terminal', default_value='true'),
        DeclareLaunchArgument('terminal_url', default_value=''),
        DeclareLaunchArgument('terminal_bind_address', default_value='0.0.0.0'),
        DeclareLaunchArgument('terminal_port', default_value='7681'),
        DeclareLaunchArgument('terminal_path', default_value='/'),
        DeclareLaunchArgument('rosboard_enabled', default_value='true'),
        DeclareLaunchArgument('rosboard_port', default_value='8888'),
        DeclareLaunchArgument(
            'terminal_workspace',
            default_value=default_workspace_root(web_share),
        ),
        ExecuteProcess(
            condition=IfCondition(LaunchConfiguration('start_terminal')),
            cmd=[
                FindExecutable(name='ttyd'),
                '-i',
                LaunchConfiguration('terminal_bind_address'),
                '-p',
                LaunchConfiguration('terminal_port'),
                '-W',
                '/bin/bash',
                terminal_shell,
                LaunchConfiguration('terminal_workspace'),
            ],
            output='screen',
        ),
        Node(
            package='rover_web',
            executable='web_gateway_node',
            name='web_gateway_node',
            output='screen',
            parameters=[
                str(web_share / 'config' / 'web.yaml'),
                {
                    'bind_address': LaunchConfiguration('bind_address'),
                    'port': ParameterValue(
                        LaunchConfiguration('port'),
                        value_type=int,
                    ),
                    'command_topic': LaunchConfiguration('command_topic'),
                    'rover_config_file': LaunchConfiguration('rover_config_file'),
                    'plans_directory': LaunchConfiguration('plans_directory'),
                    'hackathon_files_root': LaunchConfiguration('hackathon_files_root'),
                    'terminal_enabled': ParameterValue(
                        LaunchConfiguration('terminal_enabled'),
                        value_type=bool,
                    ),
                    'terminal_url': LaunchConfiguration('terminal_url'),
                    'terminal_port': ParameterValue(
                        LaunchConfiguration('terminal_port'),
                        value_type=int,
                    ),
                    'terminal_path': LaunchConfiguration('terminal_path'),
                    'rosboard_enabled': ParameterValue(
                        LaunchConfiguration('rosboard_enabled'),
                        value_type=bool,
                    ),
                    'rosboard_port': ParameterValue(
                        LaunchConfiguration('rosboard_port'),
                        value_type=int,
                    ),
                    'identity_file': str(
                        web_share / 'config' / 'robot_identity.yaml'
                    ),
                    'web_root': str(web_share / 'web'),
                    'motion_executor_path': str(
                        web_share / 'tools' / 'rover_motion_executor.py'
                    ),
                    'seed_plans_directory': str(web_share / 'plans'),
                },
            ],
        ),
    ])
