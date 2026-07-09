from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_config = str(
        Path(get_package_share_directory('rover_display'))
        / 'config'
        / 'display.yaml'
    )
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('right_panel_mode', default_value='placeholder'),
        DeclareLaunchArgument('robot_serial', default_value='1'),
        Node(
            package='rover_display',
            executable='status_display_node',
            name='rover_status_display_node',
            output='screen',
            parameters=[
                LaunchConfiguration('config_file'),
                {
                    'right_panel_mode': ParameterValue(
                        LaunchConfiguration('right_panel_mode'),
                        value_type=str,
                    ),
                    'robot_serial': ParameterValue(
                        LaunchConfiguration('robot_serial'),
                        value_type=str,
                    ),
                },
            ],
        ),
    ])
