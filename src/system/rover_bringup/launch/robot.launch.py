from __future__ import annotations

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

from rover_bringup.configuration import (
    as_launch_bool,
    bringup_config_path,
    component_enabled,
    load_profile,
    override_bool,
)


CORE_COMPONENTS = (
    'base',
    'odometry',
    'description',
    'localization',
    'twist_mux',
    'imu',
    'lidar',
    'camera',
    'vision',
    'led_strip',
    'octoliner',
    'waveshare_audio',
)


def _flag(context, profile: dict, argument: str, component: str) -> bool:
    configured = component_enabled(profile, component, False)
    return override_bool(LaunchConfiguration(argument).perform(context), configured)


def _add_if_set(arguments: dict[str, str], name: str, value) -> None:
    if value is not None and str(value).strip():
        arguments[name] = str(value)


def _bringup_include(filename: str, arguments: dict[str, str]):
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_bringup'), 'launch', filename,
        ])),
        launch_arguments=arguments.items(),
    )


def _launch_setup(context):
    profile_name = LaunchConfiguration('profile').perform(context).strip() or 'full'
    profile = load_profile(
        profile_name,
        LaunchConfiguration('profile_file').perform(context),
    )
    flags = {
        name: _flag(context, profile, f'use_{name}', name)
        for name in CORE_COMPONENTS
    }
    flags['lidar_filter'] = override_bool(
        LaunchConfiguration('use_lidar_filter').perform(context),
        flags['lidar'],
    )
    use_web = _flag(context, profile, 'use_web', 'web')
    use_display = _flag(context, profile, 'use_display', 'display')
    use_rosboard = _flag(context, profile, 'use_rosboard', 'rosboard')
    use_agent = _flag(context, profile, 'use_agent', 'agent')
    use_fleet_bridge = _flag(
        context, profile, 'use_fleet_bridge', 'fleet_bridge'
    )
    use_nav2 = _flag(context, profile, 'use_nav2', 'nav2')
    use_slam = _flag(context, profile, 'use_slam', 'slam')
    if use_nav2 and use_slam:
        return [
            LogInfo(msg='[ERROR] Nav2 and SLAM cannot run at the same time.'),
            EmitEvent(event=Shutdown(reason='conflicting motion modes')),
        ]

    requested_mode = LaunchConfiguration('mode').perform(context).strip()
    mode = requested_mode or ('navigation' if use_nav2 else 'mapping' if use_slam else 'idle')
    use_sim_time = override_bool(
        LaunchConfiguration('use_sim_time').perform(context),
        False,
    )
    robot_config_file = LaunchConfiguration('robot_config_file').perform(context).strip()
    legacy_config_file = LaunchConfiguration('config_file').perform(context).strip()
    if legacy_config_file:
        robot_config_file = legacy_config_file
    implementations_file = LaunchConfiguration('implementations_file').perform(context)
    topics_config_file = LaunchConfiguration('topics_config_file').perform(context)

    core_args = {
        'profile': 'full',
        'implementations_file': implementations_file,
        'robot_config_file': robot_config_file,
        'topics_config_file': topics_config_file,
        'use_sim_time': as_launch_bool(use_sim_time),
        'discovery_mode': LaunchConfiguration('discovery_mode').perform(context),
        'runtime_dir': LaunchConfiguration('runtime_dir').perform(context),
        'device_config': LaunchConfiguration('device_config').perform(context),
        'motor_device': LaunchConfiguration('motor_device').perform(context),
        'imu_device': LaunchConfiguration('imu_device').perform(context),
        'lidar_device': LaunchConfiguration('lidar_device').perform(context),
        'twist_mux_config_file': LaunchConfiguration('twist_mux_config_file').perform(context),
    }
    for name, enabled in flags.items():
        core_args[f'use_{name}'] = as_launch_bool(enabled)
    for name in (
        'base', 'odometry', 'localization', 'imu', 'lidar', 'lidar_filter',
        'camera', 'vision', 'led_strip', 'octoliner', 'waveshare_audio',
    ):
        _add_if_set(
            core_args,
            f'{name}_config_file',
            LaunchConfiguration(f'{name}_config_file').perform(context),
        )

    actions = [
        LogInfo(msg=f'Compatibility profile={profile_name}; motion mode={mode}'),
        _bringup_include('core.launch.py', core_args),
    ]

    if use_web or use_display or use_rosboard:
        ui_args = {
            'profile': 'full',
            'implementations_file': implementations_file,
            'topics_config_file': topics_config_file,
            'rover_config_file': robot_config_file,
            'use_web': as_launch_bool(use_web),
            'use_display': as_launch_bool(use_display),
            'use_rosboard': as_launch_bool(use_rosboard),
            'command_topic': (
                '/cmd_vel_teleop' if flags['twist_mux'] else '/cmd_vel'
            ),
        }
        for name in (
            'web_config_file', 'web_bind_address', 'web_port', 'identity_file',
            'plans_directory', 'hackathon_files_root', 'terminal_enabled',
            'start_terminal', 'terminal_bind_address', 'terminal_port',
            'terminal_path', 'terminal_url', 'terminal_workspace',
            'rosboard_port', 'display_config_file', 'display_agent_text_topic',
            'display_battery_topic', 'display_panel_mode', 'display_robot_serial',
        ):
            _add_if_set(ui_args, name, LaunchConfiguration(name).perform(context))
        actions.append(_bringup_include('ui.launch.py', ui_args))

    if use_agent or use_fleet_bridge:
        integration_args = {
            'profile': 'full',
            'implementations_file': implementations_file,
            'robot_config_file': robot_config_file,
            'topics_config_file': topics_config_file,
            'use_agent': as_launch_bool(use_agent),
            'use_fleet_bridge': as_launch_bool(use_fleet_bridge),
        }
        for name in (
            'agent_config_file', 'bridge_config_file', 'mcp_host', 'mcp_port',
            'mcp_url', 'prompt_file', 'llm_base_url', 'llm_model',
            'llm_api_key_env', 'native_tool_mode', 'timeout_s',
            'max_tool_rounds', 'mqtt_host', 'mqtt_port', 'mqtt_topic_prefix',
            'mqtt_username', 'mqtt_password_env', 'duplicate_cache_size',
            'agent_command_timeout_sec',
        ):
            _add_if_set(
                integration_args,
                name,
                LaunchConfiguration(name).perform(context),
            )
        actions.append(_bringup_include('integrations.launch.py', integration_args))

    mode_args = {
        'mode': mode,
        'implementations_file': implementations_file,
        'use_sim_time': as_launch_bool(use_sim_time),
        'use_rviz': LaunchConfiguration('use_rviz').perform(context),
        'map': LaunchConfiguration('map').perform(context),
        'nav2_params_file': LaunchConfiguration('nav2_params_file').perform(context),
        'slam_params_file': LaunchConfiguration('slam_params_file').perform(context),
        'start_delay': (
            LaunchConfiguration('nav2_start_delay').perform(context)
            if mode == 'navigation'
            else LaunchConfiguration('slam_start_delay').perform(context)
            if mode in {'mapping', 'update_map'}
            else '0.0'
        ),
    }
    actions.append(_bringup_include('mode.launch.py', mode_args))
    return actions


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('profile', default_value='full'),
        DeclareLaunchArgument('profile_file', default_value=''),
        DeclareLaunchArgument('mode', default_value=''),
        DeclareLaunchArgument('implementations_file', default_value=bringup_config_path('implementations.yaml')),
        DeclareLaunchArgument('robot_config_file', default_value=bringup_config_path('rover_v1.yaml')),
        DeclareLaunchArgument('config_file', default_value=''),
        DeclareLaunchArgument('topics_config_file', default_value=bringup_config_path('topics.yaml')),
        DeclareLaunchArgument('runtime_dir', default_value=''),
        DeclareLaunchArgument('device_config', default_value=''),
        DeclareLaunchArgument('discovery_mode', default_value=''),
        DeclareLaunchArgument('motor_device', default_value=''),
        DeclareLaunchArgument('imu_device', default_value=''),
        DeclareLaunchArgument('lidar_device', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('nav2_params_file', default_value=''),
        DeclareLaunchArgument('slam_params_file', default_value=''),
        DeclareLaunchArgument('nav2_start_delay', default_value='2.0'),
        DeclareLaunchArgument('slam_start_delay', default_value='2.0'),
        DeclareLaunchArgument('twist_mux_config_file', default_value=bringup_config_path('core', 'twist_mux.yaml')),
    ]
    for name in CORE_COMPONENTS:
        arguments.append(DeclareLaunchArgument(f'use_{name}', default_value=''))
    arguments.append(DeclareLaunchArgument('use_lidar_filter', default_value=''))
    for name in ('web', 'display', 'rosboard', 'agent', 'fleet_bridge', 'nav2', 'slam'):
        arguments.append(DeclareLaunchArgument(f'use_{name}', default_value=''))
    for name in (
        'base_config_file', 'odometry_config_file', 'localization_config_file',
        'imu_config_file', 'lidar_config_file', 'lidar_filter_config_file',
        'camera_config_file', 'vision_config_file', 'led_strip_config_file',
        'octoliner_config_file', 'waveshare_audio_config_file',
        'web_config_file', 'web_bind_address', 'web_port', 'identity_file',
        'plans_directory', 'hackathon_files_root', 'terminal_enabled',
        'start_terminal', 'terminal_bind_address', 'terminal_port',
        'terminal_path', 'terminal_url', 'terminal_workspace', 'rosboard_port',
        'display_config_file', 'display_agent_text_topic',
        'display_battery_topic', 'display_panel_mode', 'display_robot_serial',
        'agent_config_file', 'bridge_config_file', 'mcp_host', 'mcp_port',
        'mcp_url', 'prompt_file', 'llm_base_url', 'llm_model',
        'llm_api_key_env', 'native_tool_mode', 'timeout_s', 'max_tool_rounds',
        'mqtt_host', 'mqtt_port', 'mqtt_topic_prefix', 'mqtt_username',
        'mqtt_password_env', 'duplicate_cache_size', 'agent_command_timeout_sec',
    ):
        arguments.append(DeclareLaunchArgument(name, default_value=''))
    return LaunchDescription([*arguments, OpaqueFunction(function=_launch_setup)])
