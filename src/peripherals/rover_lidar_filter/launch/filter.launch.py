from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _launch_setup(context, *, default_config):
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file or config_file == '.':
        config_file = default_config
    overrides = {
        'input_topic': LaunchConfiguration('input_topic'),
        'output_topic': LaunchConfiguration('output_topic'),
        'base_frame_id': LaunchConfiguration('base_frame_id'),
        'footprint_min_x_m': ParameterValue(LaunchConfiguration('footprint_min_x_m'), value_type=float),
        'footprint_max_x_m': ParameterValue(LaunchConfiguration('footprint_max_x_m'), value_type=float),
        'footprint_min_y_m': ParameterValue(LaunchConfiguration('footprint_min_y_m'), value_type=float),
        'footprint_max_y_m': ParameterValue(LaunchConfiguration('footprint_max_y_m'), value_type=float),
        'fallback_sensor_x_m': ParameterValue(LaunchConfiguration('fallback_sensor_x_m'), value_type=float),
        'fallback_sensor_y_m': ParameterValue(LaunchConfiguration('fallback_sensor_y_m'), value_type=float),
        'fallback_sensor_yaw_rad': ParameterValue(LaunchConfiguration('fallback_sensor_yaw_rad'), value_type=float),
        'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
    }
    return [Node(
        package='rover_lidar_filter',
        executable='lidar_footprint_filter',
        name='lidar_footprint_filter',
        output='screen',
        parameters=[config_file, overrides],
    )]


def generate_launch_description():
    share = Path(get_package_share_directory('rover_lidar_filter'))
    default_config = str(share / 'config' / 'default.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('variant', default_value='default'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('input_topic', default_value='/scan'),
        DeclareLaunchArgument('output_topic', default_value='/scan_filtered'),
        DeclareLaunchArgument('base_frame_id', default_value='base_link'),
        DeclareLaunchArgument('footprint_min_x_m', default_value='-0.0878'),
        DeclareLaunchArgument('footprint_max_x_m', default_value='0.1128'),
        DeclareLaunchArgument('footprint_min_y_m', default_value='-0.0995'),
        DeclareLaunchArgument('footprint_max_y_m', default_value='0.0995'),
        DeclareLaunchArgument('fallback_sensor_x_m', default_value='0.0662'),
        DeclareLaunchArgument('fallback_sensor_y_m', default_value='0.0'),
        DeclareLaunchArgument('fallback_sensor_yaw_rad', default_value='3.141592653589793'),
        OpaqueFunction(
            function=_launch_setup,
            kwargs={'default_config': default_config},
        ),
    ])
