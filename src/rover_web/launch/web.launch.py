from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def default_rover_config_file() -> str:
    try:
        return str(
            Path(get_package_share_directory('rover_bringup'))
            / 'config'
            / 'rover.yaml'
        )
    except Exception:
        return ''


def generate_launch_description():
    web_share = Path(get_package_share_directory('rover_web'))
    rosbridge_share = Path(get_package_share_directory('rosbridge_server'))

    bind_address = LaunchConfiguration('bind_address')
    port = LaunchConfiguration('port')
    rover_config_file = LaunchConfiguration('rover_config_file')
    command_topic = LaunchConfiguration('command_topic')
    plans_directory = LaunchConfiguration('plans_directory')
    rosbridge_url = LaunchConfiguration('rosbridge_url')
    rosbridge_address = LaunchConfiguration('rosbridge_address')
    rosbridge_port = LaunchConfiguration('rosbridge_port')
    rosbridge_url_path = LaunchConfiguration('rosbridge_url_path')
    terminal_enabled = LaunchConfiguration('terminal_enabled')
    terminal_url = LaunchConfiguration('terminal_url')
    terminal_port = LaunchConfiguration('terminal_port')
    terminal_path = LaunchConfiguration('terminal_path')
    max_message_size = LaunchConfiguration('max_message_size')
    websocket_ping_interval = LaunchConfiguration('websocket_ping_interval')
    websocket_ping_timeout = LaunchConfiguration('websocket_ping_timeout')

    rosbridge_launch = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            str(rosbridge_share / 'launch' / 'rosbridge_websocket_launch.xml')
        ),
        launch_arguments={
            'port': rosbridge_port,
            'address': rosbridge_address,
            'url_path': rosbridge_url_path,
            'max_message_size': max_message_size,
            'websocket_ping_interval': websocket_ping_interval,
            'websocket_ping_timeout': websocket_ping_timeout,
        }.items(),
    )

    gateway_node = Node(
        package='rover_web',
        executable='web_gateway_node',
        name='web_gateway_node',
        output='screen',
        parameters=[
            str(web_share / 'config' / 'web.yaml'),
            {
                'bind_address': bind_address,
                'port': port,
                'identity_file': str(
                    web_share / 'config' / 'robot_identity.yaml'
                ),
                'rover_config_file': rover_config_file,
                'web_root': str(web_share / 'web'),
                'motion_executor_path': str(
                    web_share / 'tools' / 'rover_motion_executor.py'
                ),
                'seed_plans_directory': str(web_share / 'plans'),
                'plans_directory': plans_directory,
                'command_topic': command_topic,
                'rosbridge_url': rosbridge_url,
                'rosbridge_port': rosbridge_port,
                'rosbridge_path': rosbridge_url_path,
                'terminal_enabled': terminal_enabled,
                'terminal_url': terminal_url,
                'terminal_port': terminal_port,
                'terminal_path': terminal_path,
            },
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument('bind_address', default_value='127.0.0.1'),
        DeclareLaunchArgument('port', default_value='8765'),
        DeclareLaunchArgument(
            'rover_config_file',
            default_value=default_rover_config_file(),
        ),
        DeclareLaunchArgument('command_topic', default_value='/cmd_vel'),
        DeclareLaunchArgument(
            'plans_directory',
            default_value=str(
                Path.home() / '.local' / 'share' / 'sverh-rover-web' / 'plans'
            ),
        ),
        DeclareLaunchArgument('rosbridge_url', default_value=''),
        DeclareLaunchArgument('rosbridge_address', default_value='127.0.0.1'),
        DeclareLaunchArgument('rosbridge_port', default_value='9090'),
        DeclareLaunchArgument('rosbridge_url_path', default_value='/'),
        DeclareLaunchArgument('terminal_enabled', default_value='false'),
        DeclareLaunchArgument('terminal_url', default_value=''),
        DeclareLaunchArgument('terminal_port', default_value='7681'),
        DeclareLaunchArgument('terminal_path', default_value='/'),
        DeclareLaunchArgument('max_message_size', default_value='4000000'),
        DeclareLaunchArgument(
            'websocket_ping_interval',
            default_value='10.0',
        ),
        DeclareLaunchArgument(
            'websocket_ping_timeout',
            default_value='30.0',
        ),
        rosbridge_launch,
        gateway_node,
    ])
