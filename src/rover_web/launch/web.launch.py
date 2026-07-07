from pathlib import Path
import shutil

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.launch_description_sources import AnyLaunchDescriptionSource, PythonLaunchDescriptionSource
from launch.substitutions import FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


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


def as_bool(text: str) -> bool:
    return text.strip().lower() in {'1', 'true', 'yes', 'on'}


def lc(context, name: str) -> str:
    return LaunchConfiguration(name).perform(context)


def build_runtime_actions(context):
    web_share = Path(get_package_share_directory('rover_web'))
    terminal_shell = str(web_share / 'tools' / 'rover_terminal_shell.sh')
    code_server_shell = str(web_share / 'tools' / 'rover_code_server.sh')
    code_server_bin = shutil.which('code-server')
    vscode_runtime_available = code_server_bin is not None

    bind_address = lc(context, 'bind_address')
    port = lc(context, 'port').strip() or '8765'
    command_topic = lc(context, 'command_topic')
    rover_config_file = lc(context, 'rover_config_file')
    plans_directory = lc(context, 'plans_directory')
    hackathon_files_root = lc(context, 'hackathon_files_root')
    terminal_enabled = as_bool(lc(context, 'terminal_enabled'))
    start_terminal = as_bool(lc(context, 'start_terminal'))
    terminal_url = lc(context, 'terminal_url')
    terminal_bind_address = lc(context, 'terminal_bind_address')
    terminal_port = lc(context, 'terminal_port').strip() or '7681'
    terminal_path = lc(context, 'terminal_path')
    rosboard_enabled = as_bool(lc(context, 'rosboard_enabled'))
    rosboard_port = lc(context, 'rosboard_port').strip() or '8888'
    foxglove_requested = as_bool(lc(context, 'foxglove_enabled'))
    foxglove_port = lc(context, 'foxglove_port').strip() or '8766'
    vscode_enabled = as_bool(lc(context, 'vscode_enabled'))
    start_vscode = as_bool(lc(context, 'start_vscode'))
    vscode_url = lc(context, 'vscode_url')
    vscode_bind_address = lc(context, 'vscode_bind_address')
    vscode_port = lc(context, 'vscode_port').strip() or '13337'
    vscode_auth = lc(context, 'vscode_auth')
    terminal_workspace = lc(context, 'terminal_workspace')
    vscode_workspace = lc(context, 'vscode_workspace')

    foxglove_launch_path: Path | None = None
    if foxglove_requested:
        try:
            foxglove_launch_path = (
                Path(get_package_share_directory('foxglove_bridge'))
                / 'launch'
                / 'foxglove_bridge_launch.xml'
            )
        except Exception:
            foxglove_launch_path = None

    foxglove_enabled = foxglove_launch_path is not None

    actions = []
    if start_terminal:
        actions.append(ExecuteProcess(
            cmd=[
                FindExecutable(name='ttyd'),
                '-i',
                terminal_bind_address,
                '-p',
                terminal_port,
                '-W',
                '/bin/bash',
                terminal_shell,
                terminal_workspace,
            ],
            output='screen',
        ))

    if vscode_runtime_available and start_vscode and vscode_enabled:
        actions.append(ExecuteProcess(
            cmd=[
                '/bin/bash',
                code_server_shell,
                vscode_workspace,
                vscode_bind_address,
                vscode_port,
                vscode_auth,
            ],
            output='screen',
        ))
    elif vscode_enabled and not vscode_runtime_available:
        actions.append(LogInfo(
            msg='[WARN] code-server is not installed. Browser VS Code will be disabled.'
        ))

    actions.append(ExecuteProcess(
        cmd=[
            FindExecutable(name='web_gateway_node'),
            '--ros-args',
            '--params-file',
            str(web_share / 'config' / 'web.yaml'),
            '-p',
            f'bind_address:={bind_address}',
            '-p',
            f'port:={port}',
            '-p',
            f'command_topic:={command_topic}',
            '-p',
            f'rover_config_file:={rover_config_file}',
            '-p',
            f'plans_directory:={plans_directory}',
            '-p',
            f'hackathon_files_root:={hackathon_files_root}',
            '-p',
            f'terminal_enabled:={"true" if terminal_enabled else "false"}',
            '-p',
            f'terminal_url:={terminal_url}',
            '-p',
            f'terminal_port:={terminal_port}',
            '-p',
            f'terminal_path:={terminal_path}',
            '-p',
            f'rosboard_enabled:={"true" if rosboard_enabled else "false"}',
            '-p',
            f'rosboard_port:={rosboard_port}',
            '-p',
            f'foxglove_enabled:={"true" if foxglove_enabled else "false"}',
            '-p',
            f'foxglove_port:={foxglove_port}',
            '-p',
            f'vscode_enabled:={"true" if (vscode_enabled and vscode_runtime_available) else "false"}',
            '-p',
            f'vscode_url:={vscode_url}',
            '-p',
            f'vscode_port:={vscode_port}',
            '-p',
            f'vscode_auth:={vscode_auth}',
            '-p',
            f'identity_file:={str(web_share / "config" / "robot_identity.yaml")}',
            '-p',
            f'web_root:={str(web_share / "web")}',
            '-p',
            f'motion_executor_path:={str(web_share / "tools" / "rover_motion_executor.py")}',
            '-p',
            f'seed_plans_directory:={str(web_share / "plans")}',
        ],
        output='screen',
    ))

    if rosboard_enabled:
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('rosboard'), 'launch', 'rosboard.launch.py'
            ])),
            launch_arguments={
                'port': rosboard_port,
            }.items(),
        ))

    if foxglove_launch_path is not None:
        actions.append(IncludeLaunchDescription(
            AnyLaunchDescriptionSource(str(foxglove_launch_path)),
            launch_arguments={
                'address': '0.0.0.0',
                'port': foxglove_port,
            }.items(),
        ))
    elif foxglove_requested:
        actions.append(LogInfo(
            msg=(
                '[WARN] foxglove_bridge package is not installed. '
                'Foxglove button will be disabled until it is available.'
            )
        ))

    return actions


def generate_launch_description():
    web_share = Path(get_package_share_directory('rover_web'))
    actions = [
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
        DeclareLaunchArgument('foxglove_enabled', default_value='false'),
        DeclareLaunchArgument('foxglove_port', default_value='8766'),
        DeclareLaunchArgument('vscode_enabled', default_value='true'),
        DeclareLaunchArgument('start_vscode', default_value='true'),
        DeclareLaunchArgument('vscode_url', default_value=''),
        DeclareLaunchArgument('vscode_bind_address', default_value='0.0.0.0'),
        DeclareLaunchArgument('vscode_port', default_value='13337'),
        DeclareLaunchArgument('vscode_auth', default_value='password'),
        DeclareLaunchArgument(
            'terminal_workspace',
            default_value=default_workspace_root(web_share),
        ),
        DeclareLaunchArgument(
            'vscode_workspace',
            default_value=default_workspace_root(web_share),
        ),
        OpaqueFunction(function=build_runtime_actions),
    ]
    return LaunchDescription(actions)
