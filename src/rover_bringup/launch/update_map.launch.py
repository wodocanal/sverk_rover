from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    navigation_share = Path(get_package_share_directory('rover_navigation'))

    use_imu = LaunchConfiguration('use_imu')
    use_lidar = LaunchConfiguration('use_lidar')
    use_camera = LaunchConfiguration('use_camera')
    use_web = LaunchConfiguration('use_web')
    use_sim_time = LaunchConfiguration('use_sim_time')
    discovery_mode = LaunchConfiguration('discovery_mode')
    use_rviz = LaunchConfiguration('use_rviz')
    posegraph = LaunchConfiguration('posegraph')
    start_mode = LaunchConfiguration('start_mode')
    initial_x = LaunchConfiguration('initial_x')
    initial_y = LaunchConfiguration('initial_y')
    initial_yaw = LaunchConfiguration('initial_yaw')

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_bringup'), 'launch', 'robot.launch.py'
        ])),
        launch_arguments={
            'use_imu': use_imu,
            'use_lidar': use_lidar,
            'use_camera': use_camera,
            'use_web': use_web,
            'use_twist_mux': 'false',
            'use_sim_time': use_sim_time,
            'discovery_mode': discovery_mode,
        }.items(),
    )

    update_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_navigation'),
            'launch',
            'update_map.launch.py',
        ])),
        launch_arguments={
            'use_sim_time': use_sim_time,
            'posegraph': posegraph,
            'start_mode': start_mode,
            'initial_x': initial_x,
            'initial_y': initial_y,
            'initial_yaw': initial_yaw,
            'use_rviz': use_rviz,
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument('use_imu', default_value='true'),
        DeclareLaunchArgument('use_lidar', default_value='true'),
        DeclareLaunchArgument('use_camera', default_value='false'),
        DeclareLaunchArgument('use_web', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('discovery_mode', default_value='configured'),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        DeclareLaunchArgument(
            'posegraph',
            default_value=str(
                navigation_share / 'maps' / 'current' / 'map'
            ),
            description='Filename prefix without .posegraph/.data',
        ),
        DeclareLaunchArgument(
            'start_mode',
            default_value='first',
            description='first or given',
        ),
        DeclareLaunchArgument('initial_x', default_value='0.0'),
        DeclareLaunchArgument('initial_y', default_value='0.0'),
        DeclareLaunchArgument('initial_yaw', default_value='0.0'),
        robot_launch,
        TimerAction(period=2.0, actions=[update_launch]),
    ])
