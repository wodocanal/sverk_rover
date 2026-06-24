from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('port', default_value='8888'),
        Node(
            package='rosboard',
            executable='rosboard_node',
            name='rosboard',
            output='screen',
            parameters=[{
                'port': LaunchConfiguration('port'),
            }],
        ),
    ])
