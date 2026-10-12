from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('rover_vision'),
        'config',
        'path_clearance.yaml',
    )
    return LaunchDescription(
        [
            Node(
                package='rover_vision',
                executable='path_clearance_node',
                name='path_clearance_node',
                output='screen',
                parameters=[config],
                additional_env={'PYTHONNOUSERSITE': '1'},
            )
        ]
    )
