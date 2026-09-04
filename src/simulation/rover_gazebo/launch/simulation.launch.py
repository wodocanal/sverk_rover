from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
    RegisterEventHandler,
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, FindExecutable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
import yaml


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _vector(config: dict, name: str, default: list[float]) -> list[float]:
    value = config.get(name, default)
    if not isinstance(value, list) or len(value) != len(default):
        raise ValueError(f'geometry.{name} must contain {len(default)} values')
    return [float(item) for item in value]


def _launch_defaults() -> dict:
    share = Path(get_package_share_directory('rover_gazebo'))
    with (share / 'config' / 'simulation.yaml').open('r', encoding='utf-8') as stream:
        config = yaml.safe_load(stream) or {}
    return dict(config.get('rover_gazebo', {}))


def _bool_text(value) -> str:
    return 'true' if bool(value) else 'false'


def _launch_setup(context):
    defaults = _launch_defaults()
    share = Path(get_package_share_directory('rover_gazebo'))
    ros_gz_share = Path(get_package_share_directory('ros_gz_sim'))
    robot_config_value = LaunchConfiguration('robot_config_file').perform(context).strip()
    robot_config_file = Path(robot_config_value).expanduser() if robot_config_value else None
    if robot_config_file is not None:
        with robot_config_file.open('r', encoding='utf-8') as stream:
            robot_config = yaml.safe_load(stream) or {}
    else:
        robot_config = {}
    geometry = dict(robot_config.get('geometry', {}))
    encoders = dict(robot_config.get('encoders', {}))

    world_value = LaunchConfiguration('world').perform(context).strip() or 'empty'
    world_path = Path(world_value).expanduser()
    if not world_path.is_file():
        world_path = share / 'worlds' / f'{world_value.removesuffix(".sdf")}.sdf'
    if not world_path.is_file():
        raise FileNotFoundError(f'Gazebo world not found: {world_path}')

    gui = _as_bool(LaunchConfiguration('gui').perform(context))
    headless = _as_bool(LaunchConfiguration('headless_rendering').perform(context))
    gz_args = ['-r', '-v', '2']
    if not gui:
        gz_args.append('-s')
        if headless:
            gz_args.append('--headless-rendering')
    gz_args.append(str(world_path))

    chassis_xyz = _vector(geometry, 'chassis_xyz', [0.0125, 0.0, 0.0096])
    imu_xyz = _vector(geometry, 'imu_xyz', [0.0332, -0.0837, 0.0435])
    imu_rpy = _vector(geometry, 'imu_rpy', [0.0, 0.0, 1.57079632679])
    lidar_xyz = _vector(geometry, 'lidar_xyz', [0.0662, 0.0, 0.0837])
    lidar_rpy = _vector(geometry, 'lidar_rpy', [0.0, 0.0, 3.141592653589793])
    camera_xyz = _vector(geometry, 'camera_xyz', [0.105, 0.0, 0.055])
    camera_rpy = _vector(geometry, 'camera_rpy', [0.0, 0.0, 0.0])

    xacro_values = {
        'simulation': 'true',
        'right_wheel_axis_y': '1',
        'wheel_radius': geometry.get('wheel_radius_m', 0.03),
        'wheel_width': geometry.get('wheel_width_m', 0.037),
        'wheelbase': geometry.get('wheelbase_m', 0.13961),
        'track_width': geometry.get('track_width_m', 0.181),
        'chassis_length': geometry.get('chassis_length_m', 0.2006),
        'chassis_width': geometry.get('chassis_width_m', 0.199),
        'chassis_height': geometry.get('chassis_height_m', 0.0532),
        'chassis_x': chassis_xyz[0],
        'chassis_y': chassis_xyz[1],
        'chassis_z': chassis_xyz[2],
        'imu_x': imu_xyz[0],
        'imu_y': imu_xyz[1],
        'imu_z': imu_xyz[2],
        'imu_roll': imu_rpy[0],
        'imu_pitch': imu_rpy[1],
        'imu_yaw': imu_rpy[2],
        'lidar_x': lidar_xyz[0],
        'lidar_y': lidar_xyz[1],
        'lidar_z': lidar_xyz[2],
        'lidar_roll': lidar_rpy[0],
        'lidar_pitch': lidar_rpy[1],
        'lidar_yaw': lidar_rpy[2],
        'camera_x': camera_xyz[0],
        'camera_y': camera_xyz[1],
        'camera_z': camera_xyz[2],
        'camera_roll': camera_rpy[0],
        'camera_pitch': camera_rpy[1],
        'camera_yaw': camera_rpy[2],
        'controllers_file': share / 'config' / 'controllers.yaml',
        'camera_width': LaunchConfiguration('camera_width').perform(context),
        'camera_height': LaunchConfiguration('camera_height').perform(context),
        'camera_fps': LaunchConfiguration('camera_fps').perform(context),
        'lidar_samples': LaunchConfiguration('lidar_samples').perform(context),
        'lidar_rate_hz': LaunchConfiguration('lidar_rate_hz').perform(context),
        'imu_rate_hz': LaunchConfiguration('imu_rate_hz').perform(context),
    }
    command = [FindExecutable(name='xacro'), ' ', str(share / 'urdf' / 'rover.gazebo.xacro')]
    for name, value in xacro_values.items():
        command.append(f' {name}:={value}')
    robot_description = ParameterValue(Command(command), value_type=str)

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            str(ros_gz_share / 'launch' / 'gz_sim.launch.py')
        ),
        launch_arguments={'gz_args': ' '.join(gz_args)}.items(),
    )
    state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description, 'use_sim_time': True}],
    )
    spawn = Node(
        package='ros_gz_sim',
        executable='create',
        output='screen',
        arguments=[
            '-topic', 'robot_description',
            '-name', 'rover',
            '-allow_renaming', 'false',
            '-x', LaunchConfiguration('spawn_x'),
            '-y', LaunchConfiguration('spawn_y'),
            '-z', LaunchConfiguration('spawn_z'),
            '-Y', LaunchConfiguration('spawn_yaw'),
        ],
    )
    joint_state_spawner = Node(
        package='controller_manager',
        executable='spawner',
        output='screen',
        arguments=['joint_state_broadcaster', '--controller-manager', '/controller_manager'],
    )
    drive_spawner = Node(
        package='controller_manager',
        executable='spawner',
        output='screen',
        arguments=[
            'mecanum_drive_controller',
            '--controller-manager', '/controller_manager',
            '--param-file', str(share / 'config' / 'controllers.yaml'),
        ],
    )
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='rover_gazebo_bridge',
        output='screen',
        parameters=[{
            'config_file': str(share / 'config' / 'bridge.yaml'),
            'use_sim_time': True,
        }],
    )
    common_parameters = [{'use_sim_time': True}]
    twist_adapter = Node(
        package='rover_gazebo', executable='twist_adapter',
        output='screen', parameters=common_parameters,
    )
    encoder_adapter = Node(
        package='rover_gazebo', executable='encoder_adapter',
        output='screen', parameters=[{
            'use_sim_time': True,
            'wheel_radius_m': float(geometry.get('wheel_radius_m', 0.03)),
            'encoder_lines': float(encoders.get('encoder_lines', 11.0)),
            'reduction_ratio': float(encoders.get('reduction_ratio', 45.0)),
            'quadrature_factor': float(encoders.get('quadrature_factor', 4.0)),
        }],
    )
    camera_adapter = Node(
        package='rover_gazebo', executable='camera_adapter',
        output='screen', parameters=common_parameters,
    )
    mock_io = Node(
        package='rover_gazebo', executable='mock_io',
        output='screen', parameters=common_parameters,
    )
    initial_pose = Node(
        package='rover_gazebo', executable='initial_pose',
        output='screen', parameters=[{
            'use_sim_time': True,
            'x': float(LaunchConfiguration('spawn_x').perform(context)),
            'y': float(LaunchConfiguration('spawn_y').perform(context)),
            'yaw': float(LaunchConfiguration('spawn_yaw').perform(context)),
            'delay_sec': float(defaults.get('initial_pose_delay_sec', 11.0)),
        }],
    )

    return [
        LogInfo(msg=f'Gazebo world={world_path}; gui={gui}; headless_rendering={headless}'),
        SetEnvironmentVariable(
            'GZ_SIM_RESOURCE_PATH',
            f'{share}:{world_path.parent}',
        ),
        gazebo,
        bridge,
        state_publisher,
        spawn,
        RegisterEventHandler(OnProcessExit(
            target_action=spawn,
            on_exit=[joint_state_spawner],
        )),
        RegisterEventHandler(OnProcessExit(
            target_action=joint_state_spawner,
            on_exit=[drive_spawner],
        )),
        twist_adapter,
        encoder_adapter,
        camera_adapter,
        mock_io,
        *([initial_pose] if _as_bool(
            LaunchConfiguration('publish_initial_pose').perform(context)
        ) else []),
    ]


def generate_launch_description():
    defaults = _launch_defaults()
    spawn_xyz = _vector(defaults, 'spawn_xyz', [0.0, 0.0, 0.035])
    return LaunchDescription([
        DeclareLaunchArgument('world', default_value=str(defaults.get('world', 'empty'))),
        DeclareLaunchArgument('gui', default_value=_bool_text(defaults.get('gui', False))),
        DeclareLaunchArgument(
            'headless_rendering',
            default_value=_bool_text(defaults.get('headless_rendering', True)),
        ),
        DeclareLaunchArgument('robot_config_file', default_value=''),
        DeclareLaunchArgument('publish_initial_pose', default_value='false'),
        DeclareLaunchArgument('spawn_x', default_value=str(spawn_xyz[0])),
        DeclareLaunchArgument('spawn_y', default_value=str(spawn_xyz[1])),
        DeclareLaunchArgument('spawn_z', default_value=str(spawn_xyz[2])),
        DeclareLaunchArgument(
            'spawn_yaw', default_value=str(defaults.get('spawn_yaw', 0.0))
        ),
        DeclareLaunchArgument(
            'camera_width', default_value=str(defaults.get('camera_width', 640))
        ),
        DeclareLaunchArgument(
            'camera_height', default_value=str(defaults.get('camera_height', 360))
        ),
        DeclareLaunchArgument(
            'camera_fps', default_value=str(defaults.get('camera_fps', 15.0))
        ),
        DeclareLaunchArgument(
            'lidar_samples', default_value=str(defaults.get('lidar_samples', 720))
        ),
        DeclareLaunchArgument(
            'lidar_rate_hz', default_value=str(defaults.get('lidar_rate_hz', 10.0))
        ),
        DeclareLaunchArgument(
            'imu_rate_hz', default_value=str(defaults.get('imu_rate_hz', 100.0))
        ),
        OpaqueFunction(function=_launch_setup),
    ])
