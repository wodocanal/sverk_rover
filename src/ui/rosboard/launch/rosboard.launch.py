from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config_file = str(
        Path(get_package_share_directory('rosboard')) / 'config' / 'rosboard.yaml'
    )
    return LaunchDescription([
        DeclareLaunchArgument('port', default_value='8888'),
        DeclareLaunchArgument('config_file', default_value=config_file),
        DeclareLaunchArgument('variant', default_value='rosboard'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        Node(
            package='rosboard',
            executable='rosboard_node',
            name='rosboard',
            output='screen',
            additional_env={
                # Avoid user-site NumPy 2.x shadowing the distro NumPy used by
                # OpenCV/PIL on Raspberry Pi.
                'PYTHONNOUSERSITE': '1',
            },
            parameters=[LaunchConfiguration('config_file'), {
                'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                'port': ParameterValue(LaunchConfiguration('port'), value_type=int),
            }],
        ),
    ])
