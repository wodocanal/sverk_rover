from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    web_share = Path(get_package_share_directory('rover_web'))

    return LaunchDescription([
        DeclareLaunchArgument('bind_address', default_value='0.0.0.0'),
        DeclareLaunchArgument('port', default_value='8765'),
        DeclareLaunchArgument('command_topic', default_value='/cmd_vel'),
        Node(
            package='rover_web',
            executable='web_gateway_node',
            name='web_gateway_node',
            output='screen',
            parameters=[
                str(web_share / 'config' / 'web.yaml'),
                {
                    'bind_address': LaunchConfiguration('bind_address'),
                    'port': LaunchConfiguration('port'),
                    'command_topic': LaunchConfiguration('command_topic'),
                    'web_root': str(web_share / 'web'),
                },
            ],
        ),
    ])
