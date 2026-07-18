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
    use_vision = LaunchConfiguration('use_vision')
    use_display = LaunchConfiguration('use_display')
    use_led_strip = LaunchConfiguration('use_led_strip')
    use_octoliner = LaunchConfiguration('use_octoliner')
    use_waveshare_audio = LaunchConfiguration('use_waveshare_audio')
    use_web = LaunchConfiguration('use_web')
    use_sim_time = LaunchConfiguration('use_sim_time')
    use_rviz = LaunchConfiguration('use_rviz')
    map_file = LaunchConfiguration('map')
    motor_device = LaunchConfiguration('motor_device')
    imu_device = LaunchConfiguration('imu_device')
    lidar_device = LaunchConfiguration('lidar_device')
    lidar_baudrate = LaunchConfiguration('lidar_baudrate')

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_bringup'), 'launch', 'robot.launch.py'
        ])),
        launch_arguments={
            'use_imu': use_imu,
            'use_lidar': use_lidar,
            'use_camera': use_camera,
            'use_vision': use_vision,
            'use_display': use_display,
            'use_led_strip': use_led_strip,
            'use_octoliner': use_octoliner,
            'use_waveshare_audio': use_waveshare_audio,
            'use_web': use_web,
            'use_twist_mux': 'true',
            'use_sim_time': use_sim_time,
            'motor_device': motor_device,
            'imu_device': imu_device,
            'lidar_device': lidar_device,
            'lidar_baudrate': lidar_baudrate,
        }.items(),
    )

    nav_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_navigation'), 'launch', 'navigation.launch.py'
        ])),
        launch_arguments={
            'use_sim_time': use_sim_time,
            'map': map_file,
            'use_rviz': use_rviz,
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument('use_imu', default_value='true'),
        DeclareLaunchArgument('use_lidar', default_value='true'),
        DeclareLaunchArgument('use_camera', default_value='true'),
        DeclareLaunchArgument('use_vision', default_value='true'),
        DeclareLaunchArgument('use_display', default_value='false'),
        DeclareLaunchArgument('use_led_strip', default_value='false'),
        DeclareLaunchArgument('use_octoliner', default_value='false'),
        DeclareLaunchArgument('use_waveshare_audio', default_value='false'),
        DeclareLaunchArgument('use_web', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        DeclareLaunchArgument('motor_device', default_value=''),
        DeclareLaunchArgument('imu_device', default_value=''),
        DeclareLaunchArgument('lidar_device', default_value=''),
        DeclareLaunchArgument('lidar_baudrate', default_value=''),
        DeclareLaunchArgument(
            'map',
            default_value=str(
                navigation_share / 'maps' / 'current' / 'map.yaml'
            ),
        ),
        robot_launch,
        # Give hardware, TF and /scan a short head start before Nav2 activates.
        TimerAction(period=2.0, actions=[nav_launch]),
    ])
