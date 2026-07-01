from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory('rover_vision'))
    config_file = share / 'config' / 'vision.yaml'

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=str(config_file)),
        Node(
            package='rover_vision',
            executable='camera_detector_node',
            name='camera_detector_node',
            output='screen',
            parameters=[LaunchConfiguration('config_file')],
        ),
    ])
