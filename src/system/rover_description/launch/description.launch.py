from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import Command, FindExecutable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from rover_configuration import config_path, package_path, read_config


def launch_setup(context):
    geometry = read_config(LaunchConfiguration('config_file').perform(context))['geometry']
    arguments = {
        name: geometry[name + '_m']
        for name in ('wheel_radius', 'wheel_width', 'wheelbase', 'track_width',
                     'chassis_length', 'chassis_width', 'chassis_height')
    }
    for part in ('chassis', 'imu', 'lidar'):
        for axis, value in zip(('x', 'y', 'z'), geometry[part + '_xyz']):
            arguments[part + '_' + axis] = value
    for part in ('imu', 'lidar'):
        for axis, value in zip(('roll', 'pitch', 'yaw'), geometry[part + '_rpy']):
            arguments[part + '_' + axis] = value
    command = [
        FindExecutable(name='xacro'), ' ',
        package_path('rover_description', 'urdf', 'rover.urdf.xacro'),
    ]
    for name, value in arguments.items():
        command.extend([' ', name + ':=', str(value)])
    return [Node(
        package='robot_state_publisher', executable='robot_state_publisher',
        name='robot_state_publisher', output='screen',
        parameters=[{
            'robot_description': ParameterValue(Command(command), value_type=str),
            'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
        }],
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=config_path('rover_description', 'rover_v1.yaml')),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        OpaqueFunction(function=launch_setup),
    ])
