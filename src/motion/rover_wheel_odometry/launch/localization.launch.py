from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    share = Path(get_package_share_directory('rover_wheel_odometry'))
    config_dir = share / 'config' / 'localization'
    use_imu = LaunchConfiguration('use_imu')
    use_sim_time = ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool)
    overrides = {
        'use_sim_time': use_sim_time,
        'odom0': LaunchConfiguration('wheel_odometry_topic'),
        'map_frame': LaunchConfiguration('map_frame'),
        'odom_frame': LaunchConfiguration('odom_frame'),
        'base_link_frame': LaunchConfiguration('base_frame'),
        'world_frame': LaunchConfiguration('odom_frame'),
    }
    return LaunchDescription([
        DeclareLaunchArgument('use_imu', default_value='true'),
        DeclareLaunchArgument('variant', default_value='ekf'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('with_imu_config_file', default_value=str(config_dir / 'ekf_with_imu.yaml')),
        DeclareLaunchArgument('wheel_only_config_file', default_value=str(config_dir / 'ekf_wheel_only.yaml')),
        DeclareLaunchArgument('wheel_odometry_topic', default_value='/wheel/odometry'),
        DeclareLaunchArgument('imu_topic', default_value='/imu/data'),
        DeclareLaunchArgument('filtered_odometry_topic', default_value='/odom'),
        DeclareLaunchArgument('map_frame', default_value='map'),
        DeclareLaunchArgument('odom_frame', default_value='odom'),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        Node(
            package='robot_localization', executable='ekf_node',
            name='ekf_filter_node', output='screen',
            parameters=[LaunchConfiguration('with_imu_config_file'), overrides, {
                'imu0': LaunchConfiguration('imu_topic'),
            }],
            remappings=[('odometry/filtered', LaunchConfiguration('filtered_odometry_topic'))],
            condition=IfCondition(use_imu),
        ),
        Node(
            package='robot_localization', executable='ekf_node',
            name='ekf_filter_node', output='screen',
            parameters=[LaunchConfiguration('wheel_only_config_file'), overrides],
            remappings=[('odometry/filtered', LaunchConfiguration('filtered_odometry_topic'))],
            condition=UnlessCondition(use_imu),
        ),
    ])
