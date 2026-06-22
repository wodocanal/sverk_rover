from __future__ import annotations

from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, LogInfo, OpaqueFunction
from launch.events import Shutdown
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

from rover_device_manager.discovery import DEFAULT_DEVICE_CONFIG, prepare_devices


def as_bool(text: str) -> bool:
    return text.strip().lower() in ('1', 'true', 'yes', 'on')


def launch_setup(context):
    config_path = Path(LaunchConfiguration('config_file').perform(context))
    runtime_dir = LaunchConfiguration('runtime_dir').perform(context)
    device_config = LaunchConfiguration('device_config').perform(context)
    discovery_mode = LaunchConfiguration('discovery_mode').perform(context)
    use_imu = as_bool(LaunchConfiguration('use_imu').perform(context))
    use_lidar = as_bool(LaunchConfiguration('use_lidar').perform(context))
    use_camera = as_bool(LaunchConfiguration('use_camera').perform(context))
    use_mux = as_bool(LaunchConfiguration('use_twist_mux').perform(context))
    use_sim_time = as_bool(LaunchConfiguration('use_sim_time').perform(context))
    motor_override = LaunchConfiguration('motor_device').perform(context).strip() or None
    imu_override = LaunchConfiguration('imu_device').perform(context).strip() or None
    lidar_override = LaunchConfiguration('lidar_device').perform(context).strip() or None

    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    lidar_config = dict(config.get('lidar', {}))

    try:
        probe_baudrates = tuple(
            int(value) for value in lidar_config.get(
                'probe_baudrates', [460800, 115200, 256000, 1000000]
            )
        )
        results = prepare_devices(
            mode=discovery_mode,
            config_path=device_config,
            runtime_dir=runtime_dir,
            require_imu=use_imu,
            require_lidar=use_lidar,
            motor_device=motor_override,
            imu_device=imu_override,
            lidar_device=lidar_override,
            lidar_baudrates=probe_baudrates,
        )
    except Exception as exc:
        return [
            LogInfo(msg=f'[ERROR] Hardware discovery failed: {exc}'),
            EmitEvent(event=Shutdown(reason='serial device discovery failed')),
        ]

    detected = [
        f"motor controller: {results['motor_controller'].resolved_device}"
    ]
    if 'imu' in results:
        detected.append(f"IMU: {results['imu'].resolved_device}")
    if 'lidar' in results:
        detected.append(f"lidar: {results['lidar'].resolved_device}")
    actions = [LogInfo(
        msg=(
            f'Device mode={discovery_mode}; ' + '; '.join(detected)
        )
    )]

    geometry = config['geometry']
    encoders = config['encoders']
    base_params = dict(config['base_driver'])
    base_params.update({
        'serial_device': str(Path(runtime_dir) / 'motor_controller'),
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
    camera_params = dict(config.get('camera', {}))
    camera_params['use_sim_time'] = use_sim_time

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
        mux_config = str(
            Path(get_package_share_directory('rover_bringup'))
            / 'config'
            / 'twist_mux.yaml'
        )
        actions.append(Node(
            package='twist_mux',
            executable='twist_mux',
            name='twist_mux',
            output='screen',
            parameters=[mux_config],
            remappings=[('cmd_vel_out', '/cmd_vel')],
        ))

    if use_lidar:
        detected_lidar = results['lidar']
        detected_lidar_params = dict(detected_lidar.parameters)
        lidar_params = {
            'channel_type': 'serial',
            'serial_port': str(Path(runtime_dir) / 'lidar'),
            'serial_baudrate': detected_lidar.baudrate,
            'frame_id': str(lidar_config.get('frame_id', 'lidar_link')),
            'inverted': bool(lidar_config.get('inverted', False)),
            'angle_compensate': bool(lidar_config.get('angle_compensate', True)),
            'scan_mode': str(detected_lidar_params.get(
                'scan_mode', lidar_config.get('scan_mode', 'Standard')
            )),
            'scan_frequency': float(detected_lidar_params.get(
                'scan_frequency', lidar_config.get('scan_frequency', 10.0)
            )),
            'range_min': float(detected_lidar_params.get(
                'range_min', lidar_config.get('range_min', 0.17)
            )),
            'use_sim_time': use_sim_time,
        }
        actions.append(Node(
            package='sllidar_ros2',
            executable='sllidar_node',
            name='sllidar_node',
            output='screen',
            parameters=[lidar_params],
        ))

    if use_camera:
        actions.append(Node(
            package='rover_camera',
            executable='usb_camera_node',
            name='usb_camera_node',
            output='screen',
            parameters=[camera_params],
        ))

    localization = Path(
        get_package_share_directory('rover_localization')
    ) / 'config'
    if use_imu:
        imu_params.update({
            'serial_device': str(Path(runtime_dir) / 'imu'),
            'baudrate': results['imu'].baudrate,
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
    default_config = str(
        Path(get_package_share_directory('rover_bringup'))
        / 'config'
        / 'rover.yaml'
    )
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('runtime_dir', default_value='/tmp/rover_devices'),
        DeclareLaunchArgument(
            'device_config',
            default_value=DEFAULT_DEVICE_CONFIG,
            description='Persistent device setup JSON file',
        ),
        DeclareLaunchArgument(
            'discovery_mode',
            default_value='configured',
            description='configured (fast), verify, or full',
        ),
        DeclareLaunchArgument('use_imu', default_value='true'),
        DeclareLaunchArgument('use_lidar', default_value='true'),
        DeclareLaunchArgument('use_camera', default_value='false'),
        # Kept false for compatibility with the existing motion executor,
        # which publishes directly to /cmd_vel. Enable it for Nav2.
        DeclareLaunchArgument('use_twist_mux', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('motor_device', default_value=''),
        DeclareLaunchArgument('imu_device', default_value=''),
        DeclareLaunchArgument('lidar_device', default_value=''),
        OpaqueFunction(function=launch_setup),
    ])
