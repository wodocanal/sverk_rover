from pathlib import Path
import socket

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
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


def as_bool(text: str) -> bool:
    return text.strip().lower() in ('1', 'true', 'yes', 'on')


def can_bind(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def resolve_port(host: str, requested_port: int, auto_fallback: bool) -> tuple[int, bool]:
    if can_bind(host, requested_port):
        return requested_port, False
    if not auto_fallback:
        raise RuntimeError(f'Port {requested_port} is already in use on {host}')
    for candidate in range(requested_port + 1, requested_port + 21):
        if can_bind(host, candidate):
            return candidate, True
    raise RuntimeError(
        f'Port {requested_port} is busy on {host} and no fallback port was found'
    )


def launch_setup(context):
    web_share = Path(get_package_share_directory('rover_web'))
    rosbridge_share = Path(get_package_share_directory('rosbridge_server'))

    bind_address = LaunchConfiguration('bind_address').perform(context)
    port = int(LaunchConfiguration('port').perform(context))
    rover_config_file = LaunchConfiguration('rover_config_file').perform(context)
    command_topic = LaunchConfiguration('command_topic').perform(context)
    plans_directory = LaunchConfiguration('plans_directory').perform(context)
    rosbridge_url = LaunchConfiguration('rosbridge_url').perform(context)
    rosbridge_address = LaunchConfiguration('rosbridge_address').perform(context)
    rosbridge_port = int(LaunchConfiguration('rosbridge_port').perform(context))
    rosbridge_url_path = LaunchConfiguration('rosbridge_url_path').perform(context)
    terminal_enabled = LaunchConfiguration('terminal_enabled').perform(context)
    terminal_url = LaunchConfiguration('terminal_url').perform(context)
    terminal_port = LaunchConfiguration('terminal_port').perform(context)
    terminal_path = LaunchConfiguration('terminal_path').perform(context)
    max_message_size = LaunchConfiguration('max_message_size').perform(context)
    websocket_ping_interval = LaunchConfiguration(
        'websocket_ping_interval'
    ).perform(context)
    websocket_ping_timeout = LaunchConfiguration(
        'websocket_ping_timeout'
    ).perform(context)
    auto_port_fallback = as_bool(
        LaunchConfiguration('auto_port_fallback').perform(context)
    )

    gateway_port, gateway_fallback = resolve_port(
        bind_address, port, auto_port_fallback
    )
    active_rosbridge_port, rosbridge_fallback = resolve_port(
        rosbridge_address, rosbridge_port, auto_port_fallback
    )

    actions = []
    if gateway_fallback:
        actions.append(LogInfo(
            msg=(
                f'Web gateway port {port} is busy on {bind_address}; '
                f'using {gateway_port} instead'
            )
        ))
    if rosbridge_fallback:
        actions.append(LogInfo(
            msg=(
                f'rosbridge port {rosbridge_port} is busy on {rosbridge_address}; '
                f'using {active_rosbridge_port} instead'
            )
        ))

    rosbridge_launch = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            str(rosbridge_share / 'launch' / 'rosbridge_websocket_launch.xml')
        ),
        launch_arguments={
            'port': str(active_rosbridge_port),
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
                'port': gateway_port,
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
                'rosbridge_port': active_rosbridge_port,
                'rosbridge_path': rosbridge_url_path,
                'terminal_enabled': as_bool(terminal_enabled),
                'terminal_url': terminal_url,
                'terminal_port': int(terminal_port),
                'terminal_path': terminal_path,
            },
        ],
    )

    actions.extend([rosbridge_launch, gateway_node])
    return actions


def generate_launch_description():

    return LaunchDescription([
        DeclareLaunchArgument('bind_address', default_value='127.0.0.1'),
        DeclareLaunchArgument('port', default_value='8765'),
        DeclareLaunchArgument(
            'auto_port_fallback',
            default_value='true',
        ),
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
        OpaqueFunction(function=launch_setup),
    ])
