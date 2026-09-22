from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_configuration import node_parameters, package_path
from rover_configuration.launch import node_launch


def launch_rviz(context):
    parameters = node_parameters(LaunchConfiguration('config_file').perform(context), 'sllidar_node')
    frame = LaunchConfiguration('frame_id').perform(context).strip() or parameters['frame_id']
    return [Node(
        package='rviz2', executable='rviz2', name='rviz2', output='screen',
        arguments=['-d', package_path('sllidar_ros2', 'rviz', 'sllidar_ros2.rviz'), '-f', frame],
    )]


def generate_launch_description():
    description = node_launch('sllidar_ros2', 'sllidar_node', 'sllidar_node', 'lidar.yaml')
    description.add_action(OpaqueFunction(function=launch_rviz))
    return description
