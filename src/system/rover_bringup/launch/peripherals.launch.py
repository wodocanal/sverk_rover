from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

from rover_bringup.configuration import bringup_config_path


def generate_launch_description():
    core = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_bringup'), 'launch', 'core.launch.py',
        ])),
        launch_arguments={
            'profile': 'none',
            'robot_config_file': LaunchConfiguration('robot_config_file'),
            'topics_config_file': LaunchConfiguration('topics_config_file'),
            'implementations_file': LaunchConfiguration('implementations_file'),
            'discovery_mode': LaunchConfiguration('discovery_mode'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'lidar_device': LaunchConfiguration('lidar_device'),
            'use_base': 'false',
            'use_odometry': 'false',
            'use_description': 'false',
            'use_localization': 'false',
            'use_twist_mux': 'false',
            'use_imu': 'false',
            'use_lidar': LaunchConfiguration('use_lidar'),
            'use_lidar_filter': LaunchConfiguration('use_lidar'),
            'use_camera': LaunchConfiguration('use_camera'),
            'use_vision': LaunchConfiguration('use_vision'),
            'use_led_strip': LaunchConfiguration('use_led_strip'),
            'use_octoliner': LaunchConfiguration('use_octoliner'),
            'use_waveshare_audio': LaunchConfiguration('use_waveshare_audio'),
        }.items(),
    )
    return LaunchDescription([
        DeclareLaunchArgument('robot_config_file', default_value=bringup_config_path('rover_v1.yaml')),
        DeclareLaunchArgument('topics_config_file', default_value=bringup_config_path('topics.yaml')),
        DeclareLaunchArgument('implementations_file', default_value=bringup_config_path('implementations.yaml')),
        DeclareLaunchArgument('discovery_mode', default_value='configured'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('lidar_device', default_value=''),
        DeclareLaunchArgument('use_lidar', default_value='true'),
        DeclareLaunchArgument('use_camera', default_value='true'),
        DeclareLaunchArgument('use_vision', default_value='true'),
        DeclareLaunchArgument('use_led_strip', default_value='true'),
        DeclareLaunchArgument('use_octoliner', default_value='true'),
        DeclareLaunchArgument('use_waveshare_audio', default_value='false'),
        core,
    ])
