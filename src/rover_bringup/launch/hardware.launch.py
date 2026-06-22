from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    # robot.launch.py loads the persistent device setup and starts all hardware.
    return LaunchDescription([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare('rover_bringup'), 'launch', 'robot.launch.py'])
        ))
    ])
