from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_config = str(
        Path(get_package_share_directory('rover_octoliner'))
        / 'config'
        / 'octoliner.yaml'
    )
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('variant', default_value='octoliner'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        Node(
            package='rover_octoliner',
            executable='octoliner_node',
            name='octoliner_node',
            output='screen',
            parameters=[LaunchConfiguration('config_file'), {
                'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
            }],
        ),
    ])
