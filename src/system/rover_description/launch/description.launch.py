from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


XACRO_ARGUMENTS = (
    'wheel_radius', 'wheel_width', 'wheelbase', 'track_width',
    'chassis_length', 'chassis_width', 'chassis_height',
    'chassis_x', 'chassis_y', 'chassis_z',
    'imu_x', 'imu_y', 'imu_z', 'imu_roll', 'imu_pitch', 'imu_yaw',
    'lidar_x', 'lidar_y', 'lidar_z', 'lidar_roll', 'lidar_pitch', 'lidar_yaw',
    'camera_x', 'camera_y', 'camera_z',
    'camera_roll', 'camera_pitch', 'camera_yaw',
    'simulation', 'right_wheel_axis_y',
)


def generate_launch_description():
    xacro_file = PathJoinSubstitution([
        FindPackageShare('rover_description'),
        'urdf',
        [LaunchConfiguration('variant'), '.urdf.xacro'],
    ])
    command = [FindExecutable(name='xacro'), ' ', xacro_file]
    for name in XACRO_ARGUMENTS:
        command.extend([f' {name}:=', LaunchConfiguration(name)])

    description = ParameterValue(Command(command), value_type=str)
    defaults = {
        'wheel_radius': '0.03',
        'wheel_width': '0.037',
        'wheelbase': '0.13961',
        'track_width': '0.181',
        'chassis_length': '0.2006',
        'chassis_width': '0.199',
        'chassis_height': '0.0532',
        'chassis_x': '0.0125',
        'chassis_y': '0.0',
        'chassis_z': '0.0096',
        'imu_x': '0.0332',
        'imu_y': '-0.0837',
        'imu_z': '0.0435',
        'imu_roll': '0.0',
        'imu_pitch': '0.0',
        'imu_yaw': '1.57079632679',
        'lidar_x': '0.0662',
        'lidar_y': '0.0',
        'lidar_z': '0.0837',
        'lidar_roll': '0.0',
        'lidar_pitch': '0.0',
        'lidar_yaw': '3.141592653589793',
        'camera_x': '0.105',
        'camera_y': '0.0',
        'camera_z': '0.055',
        'camera_roll': '0.0',
        'camera_pitch': '0.0',
        'camera_yaw': '0.0',
        'simulation': 'false',
        'right_wheel_axis_y': '-1',
    }
    arguments = [
        DeclareLaunchArgument('variant', default_value='rover'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
    ]
    arguments.extend(
        DeclareLaunchArgument(name, default_value=value)
        for name, value in defaults.items()
    )
    return LaunchDescription([
        *arguments,
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{
                'robot_description': description,
                'use_sim_time': ParameterValue(
                    LaunchConfiguration('use_sim_time'),
                    value_type=bool,
                ),
            }],
        ),
    ])
