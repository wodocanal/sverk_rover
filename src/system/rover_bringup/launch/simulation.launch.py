from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression

from rover_bringup.configuration import as_launch_bool, bringup_config_path, read_yaml_file


def _include(package: str, launch_file: str, arguments: dict):
    source = (
        Path(get_package_share_directory(package)) / 'launch' / launch_file
    )
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(source)),
        launch_arguments=arguments.items(),
    )


def generate_launch_description():
    simulation_share = Path(get_package_share_directory('rover_gazebo'))
    defaults = read_yaml_file(
        simulation_share / 'config' / 'simulation.yaml'
    )['rover_gazebo']
    spawn_xyz = defaults['spawn_xyz']
    robot_config = LaunchConfiguration('robot_config_file')
    implementations = LaunchConfiguration('implementations_file')
    topics = LaunchConfiguration('topics_config_file')
    return LaunchDescription([
        DeclareLaunchArgument('world', default_value=str(defaults['world'])),
        DeclareLaunchArgument('gui', default_value=as_launch_bool(defaults['gui'])),
        DeclareLaunchArgument(
            'headless_rendering', default_value=as_launch_bool(defaults['headless_rendering']),
        ),
        DeclareLaunchArgument('mode', default_value='idle'),
        DeclareLaunchArgument('ui_profile', default_value='web'),
        DeclareLaunchArgument('integrations_profile', default_value='none'),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        DeclareLaunchArgument('use_vision', default_value='true'),
        DeclareLaunchArgument('spawn_x', default_value=str(spawn_xyz[0])),
        DeclareLaunchArgument('spawn_y', default_value=str(spawn_xyz[1])),
        DeclareLaunchArgument('spawn_z', default_value=str(spawn_xyz[2])),
        DeclareLaunchArgument('spawn_yaw', default_value=str(defaults['spawn_yaw'])),
        DeclareLaunchArgument(
            'robot_config_file',
            default_value=bringup_config_path('rover_v1.yaml'),
        ),
        DeclareLaunchArgument(
            'implementations_file',
            default_value=bringup_config_path('implementations.yaml'),
        ),
        DeclareLaunchArgument(
            'topics_config_file',
            default_value=bringup_config_path('topics.yaml'),
        ),
        _include('rover_gazebo', 'simulation.launch.py', {
            'world': LaunchConfiguration('world'),
            'gui': LaunchConfiguration('gui'),
            'headless_rendering': LaunchConfiguration('headless_rendering'),
            'robot_config_file': robot_config,
            'publish_initial_pose': PythonExpression([
                "'", LaunchConfiguration('mode'), "' == 'navigation'",
            ]),
            'spawn_x': LaunchConfiguration('spawn_x'),
            'spawn_y': LaunchConfiguration('spawn_y'),
            'spawn_z': LaunchConfiguration('spawn_z'),
            'spawn_yaw': LaunchConfiguration('spawn_yaw'),
        }),
        _include('rover_bringup', 'core.launch.py', {
            'profile': 'simulation',
            'simulation': 'true',
            'use_sim_time': 'true',
            'robot_config_file': robot_config,
            'implementations_file': implementations,
            'topics_config_file': topics,
            'use_vision': LaunchConfiguration('use_vision'),
        }),
        _include('rover_bringup', 'mode.launch.py', {
            'mode': LaunchConfiguration('mode'),
            'use_sim_time': 'true',
            'use_rviz': LaunchConfiguration('use_rviz'),
            'start_delay': '8.0',
            'bond_timeout': '20.0',
            'implementations_file': implementations,
        }),
        _include('rover_bringup', 'ui.launch.py', {
            'profile': LaunchConfiguration('ui_profile'),
            'use_sim_time': 'true',
            'rover_config_file': robot_config,
            'implementations_file': implementations,
            'topics_config_file': topics,
            'terminal_enabled': 'false',
            'start_terminal': 'false',
        }),
        _include('rover_bringup', 'integrations.launch.py', {
            'profile': LaunchConfiguration('integrations_profile'),
            'robot_config_file': robot_config,
            'implementations_file': implementations,
            'topics_config_file': topics,
        }),
    ])
