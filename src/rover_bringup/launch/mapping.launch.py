from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_imu = LaunchConfiguration('use_imu')
    use_lidar = LaunchConfiguration('use_lidar')
    use_camera = LaunchConfiguration('use_camera')
    use_web = LaunchConfiguration('use_web')
    use_sim_time = LaunchConfiguration('use_sim_time')
    discovery_mode = LaunchConfiguration('discovery_mode')
    use_rviz = LaunchConfiguration('use_rviz')

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

    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('rover_navigation'), 'launch', 'slam.launch.py'
        ])),
        launch_arguments={
            'use_sim_time': use_sim_time,
            'use_rviz': use_rviz,
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument('use_imu', default_value='true'),
        DeclareLaunchArgument('use_lidar', default_value='true'),
        DeclareLaunchArgument('use_camera', default_value='true'),
        DeclareLaunchArgument('use_web', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('discovery_mode', default_value='configured'),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        robot_launch,
        slam_launch,
    ])
