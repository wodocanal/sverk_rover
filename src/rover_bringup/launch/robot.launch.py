from __future__ import annotations

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    Command,
    FindExecutable,
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def as_bool(text: str) -> bool:
    return text.strip().lower() in ('1', 'true', 'yes', 'on')


def as_launch_bool(value: bool) -> str:
    return 'true' if value else 'false'


def bringup_file(directory: str, name: str) -> str:
    return str(
        Path(get_package_share_directory('rover_bringup'))
        / directory
        / name
    )


def read_yaml_file(path: str) -> dict:
    config_path = Path(path).expanduser()
    value = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    return value if isinstance(value, dict) else {}


def add_if_set(arguments: dict[str, str], key: str, value) -> None:
    if value is not None and str(value).strip():
        arguments[key] = str(value)


def launch_setup(context):
    config_file = LaunchConfiguration('config_file').perform(context)
    peripherals_config_file = LaunchConfiguration('peripherals_config_file').perform(
        context
    )
    ui_config_file = LaunchConfiguration('ui_config_file').perform(context)

    use_imu = as_bool(LaunchConfiguration('use_imu').perform(context))
    use_lidar = as_bool(LaunchConfiguration('use_lidar').perform(context))
    use_camera = as_bool(LaunchConfiguration('use_camera').perform(context))
    use_vision = as_bool(LaunchConfiguration('use_vision').perform(context))
    use_display = as_bool(LaunchConfiguration('use_display').perform(context))
    use_led_strip = as_bool(LaunchConfiguration('use_led_strip').perform(context))
    use_octoliner = as_bool(LaunchConfiguration('use_octoliner').perform(context))
    use_waveshare_audio = as_bool(
        LaunchConfiguration('use_waveshare_audio').perform(context)
    )
    use_web = as_bool(LaunchConfiguration('use_web').perform(context))
    use_rosboard = as_bool(LaunchConfiguration('use_rosboard').perform(context))
    use_mux = as_bool(LaunchConfiguration('use_twist_mux').perform(context))
    use_sim_time = as_bool(LaunchConfiguration('use_sim_time').perform(context))

    rosboard_port = LaunchConfiguration('rosboard_port').perform(context).strip() or '8888'
    display_panel_mode = LaunchConfiguration('display_panel_mode').perform(context).strip()
    display_robot_serial = LaunchConfiguration('display_robot_serial').perform(context).strip()
    motor_override = LaunchConfiguration('motor_device').perform(context).strip() or None
    imu_override = LaunchConfiguration('imu_device').perform(context).strip() or None
    lidar_override = LaunchConfiguration('lidar_device').perform(context).strip() or None
    lidar_baudrate_override = (
        LaunchConfiguration('lidar_baudrate').perform(context).strip() or None
    )

    config = read_yaml_file(config_file)
    peripherals_config = read_yaml_file(peripherals_config_file)
    lidar_config = dict(peripherals_config.get('lidar', {}))
    imu_config = dict(config.get('imu', {}))
    base_config = dict(config.get('base_driver', {}))

    motor_device = str(
        motor_override or base_config.get('serial_device', '/dev/ttyUSB0')
    )
    imu_device = str(imu_override or imu_config.get('serial_device', '/dev/ttyUSB1'))
    lidar_device = str(
        lidar_override or lidar_config.get('serial_port', '/dev/ttyUSB2')
    )
    lidar_baudrate = str(
        lidar_baudrate_override or lidar_config.get('serial_baudrate', 460800)
    )

    configured = [f'motor controller: {motor_device}']
    if use_imu:
        configured.append(f'IMU: {imu_device}')
    if use_lidar:
        configured.append(f'lidar: {lidar_device} @ {lidar_baudrate}')
    actions = [LogInfo(
        msg=(
            'Device manager disabled; using configured serial devices: '
            + '; '.join(configured)
        )
    )]

    geometry = config['geometry']
    encoders = config['encoders']
    base_params = base_config
    base_params.update({
        'serial_device': motor_device,
        'wheel_radius_m': geometry['wheel_radius_m'],
        'wheelbase_m': geometry['wheelbase_m'],
        'track_width_m': geometry['track_width_m'],
        **encoders,
        'use_sim_time': use_sim_time,
    })
    odom_params = dict(config['wheel_odometry'])
    odom_params.update({
        'wheel_radius_m': geometry['wheel_radius_m'],
        'wheelbase_m': geometry['wheelbase_m'],
        'track_width_m': geometry['track_width_m'],
        **encoders,
        'use_sim_time': use_sim_time,
    })
    imu_params = dict(config['imu'])
    imu_params['use_sim_time'] = use_sim_time

    xacro_file = PathJoinSubstitution([
        FindPackageShare('rover_description'), 'urdf', 'rover.urdf.xacro'
    ])
    imu_xyz, imu_rpy = geometry['imu_xyz'], geometry['imu_rpy']
    lidar_xyz = geometry.get('lidar_xyz', [0.0, 0.0, 0.10])
    lidar_rpy = geometry.get('lidar_rpy', [0.0, 0.0, 0.0])
    robot_description = ParameterValue(Command([
        FindExecutable(name='xacro'), ' ', xacro_file,
        ' wheel_radius:=', str(geometry['wheel_radius_m']),
        ' wheel_width:=', str(geometry['wheel_width_m']),
        ' wheelbase:=', str(geometry['wheelbase_m']),
        ' track_width:=', str(geometry['track_width_m']),
        ' chassis_length:=', str(geometry['chassis_length_m']),
        ' chassis_width:=', str(geometry['chassis_width_m']),
        ' chassis_height:=', str(geometry['chassis_height_m']),
        ' imu_x:=', str(imu_xyz[0]),
        ' imu_y:=', str(imu_xyz[1]),
        ' imu_z:=', str(imu_xyz[2]),
        ' imu_roll:=', str(imu_rpy[0]),
        ' imu_pitch:=', str(imu_rpy[1]),
        ' imu_yaw:=', str(imu_rpy[2]),
        ' lidar_x:=', str(lidar_xyz[0]),
        ' lidar_y:=', str(lidar_xyz[1]),
        ' lidar_z:=', str(lidar_xyz[2]),
        ' lidar_roll:=', str(lidar_rpy[0]),
        ' lidar_pitch:=', str(lidar_rpy[1]),
        ' lidar_yaw:=', str(lidar_rpy[2]),
    ]), value_type=str)

    actions.extend([
        Node(
            package='rover_base_driver',
            executable='base_driver_node',
            name='base_driver_node',
            output='screen',
            parameters=[base_params],
        ),
        Node(
            package='rover_wheel_odometry',
            executable='wheel_odometry_node',
            name='wheel_odometry_node',
            output='screen',
            parameters=[odom_params],
        ),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{
                'robot_description': robot_description,
                'use_sim_time': use_sim_time,
            }],
        ),
    ])

    if use_mux:
        mux_config = bringup_file('config', 'twist_mux.yaml')
        actions.append(Node(
            package='twist_mux',
            executable='twist_mux',
            name='twist_mux',
            output='screen',
            parameters=[mux_config],
            remappings=[('cmd_vel_out', '/cmd_vel')],
        ))

    if (
        use_lidar
        or use_camera
        or use_vision
        or use_led_strip
        or use_octoliner
        or use_waveshare_audio
    ):
        peripheral_arguments = {
            'config_file': peripherals_config_file,
            'use_lidar': as_launch_bool(use_lidar),
            'use_camera': as_launch_bool(use_camera),
            'use_vision': as_launch_bool(use_vision),
            'use_led_strip': as_launch_bool(use_led_strip),
            'use_octoliner': as_launch_bool(use_octoliner),
            'use_waveshare_audio': as_launch_bool(use_waveshare_audio),
            'use_sim_time': as_launch_bool(use_sim_time),
        }
        if use_lidar:
            peripheral_arguments.update({
                'lidar_device': lidar_device,
                'lidar_baudrate': lidar_baudrate,
            })
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('rover_bringup'), 'launch', 'peripherals.launch.py'
            ])),
            launch_arguments=peripheral_arguments.items(),
        ))

    if use_web or use_display or use_rosboard:
        web_command_topic = '/cmd_vel_teleop' if use_mux else '/cmd_vel'
        ui_arguments = {
            'config_file': ui_config_file,
            'use_web': as_launch_bool(use_web),
            'use_display': as_launch_bool(use_display),
            'use_rosboard': as_launch_bool(use_rosboard),
            'command_topic': web_command_topic,
            'rosboard_port': rosboard_port,
        }
        add_if_set(ui_arguments, 'display_panel_mode', display_panel_mode)
        add_if_set(ui_arguments, 'display_robot_serial', display_robot_serial)
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('rover_bringup'), 'launch', 'ui.launch.py'
            ])),
            launch_arguments=ui_arguments.items(),
        ))

    localization = Path(
        get_package_share_directory('rover_localization')
    ) / 'config'
    if use_imu:
        imu_params.update({
            'serial_device': imu_device,
        })
        actions.extend([
            Node(
                package='rover_imu',
                executable='yahboom_imu_node',
                name='yahboom_imu_node',
                output='screen',
                parameters=[imu_params],
            ),
            Node(
                package='robot_localization',
                executable='ekf_node',
                name='ekf_filter_node',
                output='screen',
                parameters=[str(localization / 'ekf_with_imu.yaml')],
                remappings=[('odometry/filtered', '/odom')],
            ),
        ])
    else:
        actions.append(Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node',
            output='screen',
            parameters=[str(localization / 'ekf_wheel_only.yaml')],
            remappings=[('odometry/filtered', '/odom')],
        ))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'config_file',
            default_value=bringup_file('config', 'rover.yaml'),
        ),
        DeclareLaunchArgument(
            'peripherals_config_file',
            default_value=bringup_file('config', 'peripherals.yaml'),
        ),
        DeclareLaunchArgument(
            'ui_config_file',
            default_value=bringup_file('config', 'ui.yaml'),
        ),
        DeclareLaunchArgument('use_imu', default_value='true'),
        DeclareLaunchArgument('use_lidar', default_value='true'),
        DeclareLaunchArgument('use_camera', default_value='true'),
        DeclareLaunchArgument('use_vision', default_value='true'),
        DeclareLaunchArgument('use_display', default_value='false'),
        DeclareLaunchArgument(
            'display_panel_mode',
            default_value='',
            description='Optional touchscreen right panel override: placeholder or agent',
        ),
        DeclareLaunchArgument(
            'display_robot_serial',
            default_value='',
            description='Optional touchscreen rover serial suffix',
        ),
        DeclareLaunchArgument('use_led_strip', default_value='true'),
        DeclareLaunchArgument('use_octoliner', default_value='true'),
        DeclareLaunchArgument('use_waveshare_audio', default_value='false'),
        DeclareLaunchArgument('use_web', default_value='true'),
        DeclareLaunchArgument('use_rosboard', default_value='true'),
        DeclareLaunchArgument('rosboard_port', default_value='8888'),
        # Kept false for compatibility with the existing motion executor,
        # which publishes directly to /cmd_vel. Enable it for Nav2.
        DeclareLaunchArgument('use_twist_mux', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('motor_device', default_value=''),
        DeclareLaunchArgument('imu_device', default_value=''),
        DeclareLaunchArgument('lidar_device', default_value=''),
        DeclareLaunchArgument('lidar_baudrate', default_value=''),
        OpaqueFunction(function=launch_setup),
    ])
