from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
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


def _flag(context, profile_config: dict, name: str) -> bool:
    configured = component_enabled(profile_config, name, False)
    return override_bool(LaunchConfiguration(f'use_{name}').perform(context), configured)


def _add_if_set(arguments: dict[str, str], name: str, value) -> None:
    if value is not None and str(value).strip():
        arguments[name] = str(value)


def _include(implementations: dict, name: str, arguments: dict[str, str]):
    selected = implementation(implementations, 'ui', name)
    source = (
        Path(get_package_share_directory(selected['package']))
        / 'launch'
        / selected['launch']
    )
    launch_arguments = dict(arguments)
    _add_if_set(launch_arguments, 'variant', selected['variant'])
    include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(source)),
        launch_arguments=launch_arguments.items(),
    )
    return GroupAction(
        actions=[include],
        scoped=True,
        forwarding=False,
        launch_configurations=launch_arguments,
    )


def _launch_setup(context):
    profile_name = LaunchConfiguration('profile').perform(context).strip() or 'full'
    profile = load_layer_profile(
        'ui',
        profile_name,
        LaunchConfiguration('profile_file').perform(context),
    )
    implementations = load_implementations(
        LaunchConfiguration('implementations_file').perform(context)
    )
    topics = dict(read_yaml_file(
        LaunchConfiguration('topics_config_file').perform(context)
    ).get('topics', {}))
    use_web = _flag(context, profile, 'web')
    use_display = _flag(context, profile, 'display')
    use_rosboard = _flag(context, profile, 'rosboard')
    robot_config_file = LaunchConfiguration('rover_config_file').perform(context).strip()
    if not robot_config_file:
        robot_config_file = bringup_config_path('rover_v1.yaml')

    actions = [LogInfo(msg=f'UI profile={profile_name}')]
    sim_time = LaunchConfiguration('use_sim_time').perform(context)
    if use_web:
        args = {
            'use_sim_time': sim_time,
            'rover_config_file': robot_config_file,
            'identity_file': (
                LaunchConfiguration('identity_file').perform(context).strip()
                or robot_config_file
            ),
            'command_topic': (
                LaunchConfiguration('command_topic').perform(context).strip()
                or topics.get('cmd_vel_teleop', '/cmd_vel_teleop')
            ),
            'rosboard_enabled': 'true' if use_rosboard else 'false',
        }
        for launch_name, package_name in (
            ('web_config_file', 'config_file'),
            ('web_bind_address', 'bind_address'),
            ('web_port', 'port'),
            ('plans_directory', 'plans_directory'),
            ('hackathon_files_root', 'hackathon_files_root'),
            ('terminal_enabled', 'terminal_enabled'),
            ('start_terminal', 'start_terminal'),
            ('terminal_bind_address', 'terminal_bind_address'),
            ('terminal_port', 'terminal_port'),
            ('terminal_path', 'terminal_path'),
            ('terminal_url', 'terminal_url'),
            ('terminal_workspace', 'terminal_workspace'),
            ('rosboard_port', 'rosboard_port'),
        ):
            _add_if_set(
                args,
                package_name,
                LaunchConfiguration(launch_name).perform(context),
            )
        actions.append(_include(implementations, 'web', args))

    if use_rosboard:
        args = {'use_sim_time': sim_time}
        _add_if_set(args, 'port', LaunchConfiguration('rosboard_port').perform(context))
        _add_if_set(args, 'config_file', LaunchConfiguration('rosboard_config_file').perform(context))
        actions.append(_include(implementations, 'rosboard', args))

    if use_display:
        args = {'use_sim_time': sim_time}
        for launch_name, package_name in (
            ('display_config_file', 'config_file'),
            ('display_panel_mode', 'right_panel_mode'),
            ('display_robot_serial', 'robot_serial'),
            ('display_agent_text_topic', 'agent_text_topic'),
            ('display_battery_topic', 'battery_topic'),
        ):
            _add_if_set(
                args,
                package_name,
                LaunchConfiguration(launch_name).perform(context),
            )
        actions.append(_include(implementations, 'display', args))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('profile', default_value='full'),
        DeclareLaunchArgument('profile_file', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('implementations_file', default_value=bringup_config_path('implementations.yaml')),
        DeclareLaunchArgument('topics_config_file', default_value=bringup_config_path('topics.yaml')),
        DeclareLaunchArgument('use_web', default_value=''),
        DeclareLaunchArgument('use_display', default_value=''),
        DeclareLaunchArgument('use_rosboard', default_value=''),
        DeclareLaunchArgument('web_config_file', default_value=''),
        DeclareLaunchArgument('web_bind_address', default_value=''),
        DeclareLaunchArgument('web_port', default_value=''),
        DeclareLaunchArgument('command_topic', default_value=''),
        DeclareLaunchArgument('identity_file', default_value=''),
        DeclareLaunchArgument('rover_config_file', default_value=''),
        DeclareLaunchArgument('plans_directory', default_value=''),
        DeclareLaunchArgument('hackathon_files_root', default_value=''),
        DeclareLaunchArgument('terminal_enabled', default_value=''),
        DeclareLaunchArgument('start_terminal', default_value=''),
        DeclareLaunchArgument('terminal_bind_address', default_value=''),
        DeclareLaunchArgument('terminal_port', default_value=''),
        DeclareLaunchArgument('terminal_path', default_value=''),
        DeclareLaunchArgument('terminal_url', default_value=''),
        DeclareLaunchArgument('terminal_workspace', default_value=''),
        DeclareLaunchArgument('rosboard_port', default_value=''),
        DeclareLaunchArgument('rosboard_config_file', default_value=''),
        DeclareLaunchArgument('display_config_file', default_value=''),
        DeclareLaunchArgument('display_agent_text_topic', default_value=''),
        DeclareLaunchArgument('display_battery_topic', default_value=''),
        DeclareLaunchArgument('display_panel_mode', default_value=''),
        DeclareLaunchArgument('display_robot_serial', default_value=''),
        OpaqueFunction(function=_launch_setup),
    ])
