from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
    TimerAction,
)
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from rover_bringup.configuration import (
    as_launch_bool,
    bringup_config_path,
    implementation,
    load_implementations,
    override_bool,
)


def _add_if_set(arguments: dict[str, str], name: str, value) -> None:
    if value is not None and str(value).strip():
        arguments[name] = str(value)


def _launch_setup(context):
    mode = LaunchConfiguration('mode').perform(context).strip() or 'idle'
    if mode == 'idle':
        return [LogInfo(msg='Motion mode=idle; Nav2 and SLAM are stopped')]
    if mode not in {'navigation', 'mapping', 'update_map'}:
        return [
            LogInfo(msg=f'[ERROR] Unknown motion mode: {mode}'),
            EmitEvent(event=Shutdown(reason='unknown motion mode')),
        ]

    implementations = load_implementations(
        LaunchConfiguration('implementations_file').perform(context)
    )
    selected = implementation(implementations, 'modes', mode)
    launch_file = (
        Path(get_package_share_directory(selected['package']))
        / 'launch'
        / selected['launch']
    )
    use_sim_time = override_bool(
        LaunchConfiguration('use_sim_time').perform(context),
        False,
    )
    args = {
        'use_sim_time': as_launch_bool(use_sim_time),
        'use_rviz': LaunchConfiguration('use_rviz').perform(context),
        'autostart': LaunchConfiguration('autostart').perform(context),
        'bond_timeout': LaunchConfiguration('bond_timeout').perform(context),
    }
    _add_if_set(args, 'variant', selected['variant'])
    if mode == 'navigation':
        _add_if_set(args, 'map', LaunchConfiguration('map').perform(context))
        _add_if_set(args, 'params_file', LaunchConfiguration('nav2_params_file').perform(context))
    else:
        _add_if_set(args, 'params_file', LaunchConfiguration('slam_params_file').perform(context))
    if mode == 'update_map':
        _add_if_set(args, 'posegraph', LaunchConfiguration('posegraph_file').perform(context))
        for name in ('start_mode', 'initial_x', 'initial_y', 'initial_yaw'):
            _add_if_set(args, name, LaunchConfiguration(name).perform(context))

    include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(launch_file)),
        launch_arguments=args.items(),
    )
    delay = float(LaunchConfiguration('start_delay').perform(context).strip() or '0.0')
    action = TimerAction(period=delay, actions=[include]) if delay > 0 else include
    return [LogInfo(msg=f'Motion mode={mode}'), action]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('mode', default_value='idle'),
        DeclareLaunchArgument('implementations_file', default_value=bringup_config_path('implementations.yaml')),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        DeclareLaunchArgument('autostart', default_value='true'),
        DeclareLaunchArgument('bond_timeout', default_value='4.0'),
        DeclareLaunchArgument('start_delay', default_value='0.0'),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('nav2_params_file', default_value=''),
        DeclareLaunchArgument('slam_params_file', default_value=''),
        DeclareLaunchArgument('posegraph_file', default_value=''),
        DeclareLaunchArgument('start_mode', default_value='first'),
        DeclareLaunchArgument('initial_x', default_value='0.0'),
        DeclareLaunchArgument('initial_y', default_value='0.0'),
        DeclareLaunchArgument('initial_yaw', default_value='0.0'),
        OpaqueFunction(function=_launch_setup),
    ])
