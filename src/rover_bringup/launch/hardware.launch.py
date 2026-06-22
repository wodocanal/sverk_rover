from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution


def generate_launch_description():
    use_camera = LaunchConfiguration('use_camera')
    # robot.launch.py loads the persistent device setup and starts all hardware.
    return LaunchDescription([
        DeclareLaunchArgument('use_camera', default_value='false'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare('rover_bringup'), 'launch', 'robot.launch.py'])
        ), launch_arguments={'use_camera': use_camera}.items())
    ])
