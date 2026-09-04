from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_bringup.configuration import (
    as_launch_bool,
    bringup_config_path,
    component_enabled,
    implementation,
    load_implementations,
    load_layer_profile,
    override_bool,
    read_yaml_file,
)
from rover_device_manager.discovery import DEFAULT_DEVICE_CONFIG, prepare_devices


CORE_COMPONENTS = (
    'base',
    'odometry',
    'description',
    'localization',
    'twist_mux',
    'imu',
    'lidar',
    'lidar_filter',
    'camera',
    'vision',
    'led_strip',
    'octoliner',
    'waveshare_audio',
)


def _flag(context, profile_config: dict, name: str) -> bool:
    configured = component_enabled(profile_config, name, False)
    return override_bool(LaunchConfiguration(f'use_{name}').perform(context), configured)


def _add_if_set(arguments: dict[str, str], name: str, value) -> None:
    if value is not None and str(value).strip():
        arguments[name] = str(value)


def _include(
    implementations: dict,
    section: str,
    name: str,
    arguments: dict[str, str],
) -> GroupAction:
    selected = implementation(implementations, section, name)
    launch_file = (
        Path(get_package_share_directory(selected['package']))
        / 'launch'
        / selected['launch']
    )
    launch_arguments = dict(arguments)
    _add_if_set(launch_arguments, 'variant', selected['variant'])
    include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(launch_file)),
        launch_arguments=launch_arguments.items(),
    )
    return GroupAction(
        actions=[include], scoped=True, forwarding=False,
        launch_configurations=launch_arguments,
    )


def _config_override(context, component: str, arguments: dict[str, str]) -> None:
    value = LaunchConfiguration(f'{component}_config_file').perform(context).strip()
    _add_if_set(arguments, 'config_file', value)


def _launch_setup(context):
    profile_name = LaunchConfiguration('profile').perform(context).strip() or 'full'
    profile_config = load_layer_profile(
        'core',
        profile_name,
        LaunchConfiguration('profile_file').perform(context),
    )
    implementations = load_implementations(
        LaunchConfiguration('implementations_file').perform(context)
    )
    robot_config_file = LaunchConfiguration('robot_config_file').perform(context).strip()
    topics_config_file = LaunchConfiguration('topics_config_file').perform(context).strip()
    robot_config = read_yaml_file(robot_config_file)
    topic_config = read_yaml_file(topics_config_file)
    geometry = dict(robot_config.get('geometry', {}))
    encoders = dict(robot_config.get('encoders', {}))
    base_calibration = dict(robot_config.get('base_driver', {}))
    odometry_calibration = dict(robot_config.get('wheel_odometry', {}))
    imu_calibration = dict(robot_config.get('imu', {}))
    topics = dict(topic_config.get('topics', {}))
    frames = dict(topic_config.get('frames', {}))
    enabled = {name: _flag(context, profile_config, name) for name in CORE_COMPONENTS}
    use_sim_time = override_bool(
        LaunchConfiguration('use_sim_time').perform(context),
        False,
    )
    simulation = override_bool(
        LaunchConfiguration('simulation').perform(context),
        False,
    )

    if enabled['vision'] and not enabled['camera']:
        enabled['vision'] = False

    device_manager_share = Path(get_package_share_directory('rover_device_manager'))
    manager_file = LaunchConfiguration('device_manager_config_file').perform(context).strip()
    if not manager_file:
        manager_file = str(device_manager_share / 'config' / 'device_manager.yaml')
    manager_config = dict(read_yaml_file(manager_file).get('device_manager', {}))
    runtime_dir = (
        LaunchConfiguration('runtime_dir').perform(context).strip()
        or str(manager_config.get('runtime_dir', '/tmp/rover_devices'))
    )
    device_config = (
        LaunchConfiguration('device_config').perform(context).strip()
        or str(manager_config.get('device_config', DEFAULT_DEVICE_CONFIG))
    )
    device_config = str(Path(device_config).expanduser())
    discovery_mode = (
        LaunchConfiguration('discovery_mode').perform(context).strip()
        or str(manager_config.get('discovery_mode', 'configured'))
    )
    motor_override = LaunchConfiguration('motor_device').perform(context).strip() or None
    imu_override = LaunchConfiguration('imu_device').perform(context).strip() or None
    lidar_override = LaunchConfiguration('lidar_device').perform(context).strip() or None

    results = {}
    if not simulation and (enabled['base'] or enabled['imu'] or enabled['lidar']):
        try:
            results = prepare_devices(
                mode=discovery_mode,
                config_path=device_config,
                runtime_dir=runtime_dir,
                require_motor=enabled['base'],
                require_imu=enabled['imu'],
                require_lidar=enabled['lidar'],
                motor_device=motor_override,
                imu_device=imu_override,
                lidar_device=lidar_override,
                lidar_baudrates=(460800, 115200, 256000, 1000000),
            )
        except Exception as exc:
            return [
                LogInfo(msg=f'[ERROR] Hardware discovery failed: {exc}'),
                EmitEvent(event=Shutdown(reason='serial device discovery failed')),
            ]

    actions = [LogInfo(msg=(
        f'Core profile={profile_name}; simulation={simulation}; '
        f'discovery={"disabled" if simulation else discovery_mode}'
    ))]
    sim_time = as_launch_bool(use_sim_time)
    wheel_radius = geometry.get('wheel_radius_m', 0.03)
    wheelbase = geometry.get('wheelbase_m', 0.13961)
    track_width = geometry.get('track_width_m', 0.181)

    if enabled['base'] and not simulation:
        args = {
            'use_sim_time': sim_time,
            'serial_device': str(Path(runtime_dir) / 'motor_controller'),
            'cmd_vel_topic': topics.get('cmd_vel', '/cmd_vel'),
            'wheel_radius_m': str(wheel_radius),
            'wheelbase_m': str(wheelbase),
            'track_width_m': str(track_width),
            'encoder_lines': str(encoders.get('encoder_lines', 11.0)),
            'reduction_ratio': str(encoders.get('reduction_ratio', 45.0)),
            'quadrature_factor': str(encoders.get('quadrature_factor', 4.0)),
        }
        for name in (
            'motor_command_order', 'motor_command_signs',
            'encoder_feedback_order', 'encoder_feedback_signs',
        ):
            if name in base_calibration:
                args[name] = repr(base_calibration[name])
        if results:
            args['baudrate'] = str(results['motor_controller'].baudrate)
        _config_override(context, 'base', args)
        actions.append(_include(implementations, 'components', 'base', args))

    if enabled['odometry']:
        args = {
            'use_sim_time': sim_time,
            'encoder_topic': topics.get('wheel_encoders', '/wheel/encoders'),
            'odometry_topic': topics.get('wheel_odometry', '/wheel/odometry'),
            'odom_frame_id': frames.get('odom', 'odom'),
            'base_frame_id': frames.get('base', 'base_link'),
            'wheel_radius_m': str(wheel_radius),
            'wheelbase_m': str(wheelbase),
            'track_width_m': str(track_width),
            'encoder_lines': str(encoders.get('encoder_lines', 11.0)),
            'reduction_ratio': str(encoders.get('reduction_ratio', 45.0)),
            'quadrature_factor': str(encoders.get('quadrature_factor', 4.0)),
            'x_multiplier': str(odometry_calibration.get('x_multiplier', 1.0)),
            'y_multiplier': str(odometry_calibration.get('y_multiplier', 1.0)),
            'yaw_multiplier': str(odometry_calibration.get('yaw_multiplier', 1.0)),
        }
        _config_override(context, 'odometry', args)
        actions.append(_include(implementations, 'components', 'odometry', args))

    if enabled['description']:
        chassis_xyz = geometry.get('chassis_xyz', [0.0125, 0.0, 0.0096])
        imu_xyz = geometry.get('imu_xyz', [0.0332, -0.0837, 0.0435])
        imu_rpy = geometry.get('imu_rpy', [0.0, 0.0, 1.57079632679])
        lidar_xyz = geometry.get('lidar_xyz', [0.0662, 0.0, 0.0837])
        lidar_rpy = geometry.get('lidar_rpy', [0.0, 0.0, 3.141592653589793])
        camera_xyz = geometry.get('camera_xyz', [0.105, 0.0, 0.055])
        camera_rpy = geometry.get('camera_rpy', [0.0, 0.0, 0.0])
        args = {
            'use_sim_time': sim_time,
            'wheel_radius': str(wheel_radius),
            'wheel_width': str(geometry.get('wheel_width_m', 0.037)),
            'wheelbase': str(wheelbase),
            'track_width': str(track_width),
            'chassis_length': str(geometry.get('chassis_length_m', 0.2006)),
            'chassis_width': str(geometry.get('chassis_width_m', 0.199)),
            'chassis_height': str(geometry.get('chassis_height_m', 0.0532)),
            'chassis_x': str(chassis_xyz[0]),
            'chassis_y': str(chassis_xyz[1]),
            'chassis_z': str(chassis_xyz[2]),
            'imu_x': str(imu_xyz[0]),
            'imu_y': str(imu_xyz[1]),
            'imu_z': str(imu_xyz[2]),
            'imu_roll': str(imu_rpy[0]),
            'imu_pitch': str(imu_rpy[1]),
            'imu_yaw': str(imu_rpy[2]),
            'lidar_x': str(lidar_xyz[0]),
            'lidar_y': str(lidar_xyz[1]),
            'lidar_z': str(lidar_xyz[2]),
            'lidar_roll': str(lidar_rpy[0]),
            'lidar_pitch': str(lidar_rpy[1]),
            'lidar_yaw': str(lidar_rpy[2]),
            'camera_x': str(camera_xyz[0]),
            'camera_y': str(camera_xyz[1]),
            'camera_z': str(camera_xyz[2]),
            'camera_roll': str(camera_rpy[0]),
            'camera_pitch': str(camera_rpy[1]),
            'camera_yaw': str(camera_rpy[2]),
        }
        actions.append(_include(implementations, 'components', 'description', args))

    if enabled['twist_mux']:
        mux_file = LaunchConfiguration('twist_mux_config_file').perform(context).strip()
        actions.append(Node(
            package='twist_mux',
            executable='twist_mux',
            name='twist_mux',
            output='screen',
            parameters=[mux_file, {'use_sim_time': use_sim_time}],
            remappings=[('cmd_vel_out', topics.get('cmd_vel', '/cmd_vel'))],
        ))

    if enabled['imu'] and not simulation:
        args = {
            'use_sim_time': sim_time,
            'serial_device': str(Path(runtime_dir) / 'imu'),
            'baudrate': str(results['imu'].baudrate),
            'frame_id': frames.get('imu', 'imu_link'),
            'imu_topic': topics.get('imu_data', '/imu/data'),
            'mag_topic': topics.get('imu_mag', '/imu/mag'),
            'euler_topic': topics.get('imu_euler', '/imu/euler'),
            'frame_count_topic': topics.get('imu_frame_count', '/imu/valid_frame_count'),
            'axis_map': repr(imu_calibration.get('axis_map', [0, 1, 2])),
            'axis_signs': repr(imu_calibration.get('axis_signs', [1, 1, 1])),
        }
        _config_override(context, 'imu', args)
        actions.append(_include(implementations, 'components', 'imu', args))

    if enabled['lidar'] and not simulation:
        detected = results['lidar']
        lidar_parameters = dict(detected.parameters)
        args = {
            'use_sim_time': sim_time,
            'serial_port': str(Path(runtime_dir) / 'lidar'),
            'serial_baudrate': str(detected.baudrate),
            'frame_id': frames.get('lidar', 'lidar_link'),
            'scan_topic': topics.get('scan_raw', '/scan'),
        }
        for name in ('scan_mode', 'scan_frequency', 'range_min'):
            _add_if_set(args, name, lidar_parameters.get(name))
        _config_override(context, 'lidar', args)
        actions.append(_include(implementations, 'components', 'lidar', args))

    if enabled['lidar'] and enabled['lidar_filter']:
        chassis_xyz = geometry.get('chassis_xyz', [0.0125, 0.0, 0.0096])
        lidar_xyz = geometry.get('lidar_xyz', [0.0662, 0.0, 0.0837])
        lidar_rpy = geometry.get('lidar_rpy', [0.0, 0.0, 3.141592653589793])
        half_length = float(geometry.get('chassis_length_m', 0.2006)) / 2.0
        half_width = float(geometry.get('chassis_width_m', 0.199)) / 2.0
        args = {
            'use_sim_time': sim_time,
            'input_topic': topics.get('scan_raw', '/scan'),
            'output_topic': topics.get('scan', '/scan_filtered'),
            'base_frame_id': frames.get('base', 'base_link'),
            'footprint_min_x_m': str(float(chassis_xyz[0]) - half_length),
            'footprint_max_x_m': str(float(chassis_xyz[0]) + half_length),
            'footprint_min_y_m': str(float(chassis_xyz[1]) - half_width),
            'footprint_max_y_m': str(float(chassis_xyz[1]) + half_width),
            'fallback_sensor_x_m': str(lidar_xyz[0]),
            'fallback_sensor_y_m': str(lidar_xyz[1]),
            'fallback_sensor_yaw_rad': str(lidar_rpy[2]),
        }
        _config_override(context, 'lidar_filter', args)
        actions.append(_include(implementations, 'components', 'lidar_filter', args))

    if enabled['camera'] and not simulation:
        args = {
            'use_sim_time': sim_time,
            'image_topic': topics.get('image_raw', '/image_raw'),
            'compressed_image_topic': topics.get('image_raw_compressed', '/image_raw/compressed'),
            'frame_id': frames.get('camera', 'camera_optical_frame'),
        }
        _config_override(context, 'camera', args)
        actions.append(_include(implementations, 'components', 'camera', args))

    if enabled['vision']:
        args = {
            'use_sim_time': sim_time,
            'input_topic': topics.get('image_raw', '/image_raw'),
            'processed_image_topic': topics.get('image_processed', '/image_processed'),
            'processed_compressed_image_topic': topics.get('image_processed_compressed', '/image_processed/compressed'),
            'detections_topic': topics.get('detections', '/detections'),
            'frame_id': frames.get('camera', 'camera_optical_frame'),
        }
        _config_override(context, 'vision', args)
        actions.append(_include(implementations, 'components', 'vision', args))

    for name in ('led_strip', 'octoliner'):
        if enabled[name]:
            args = {'use_sim_time': sim_time}
            _config_override(context, name, args)
            actions.append(_include(implementations, 'components', name, args))

    if enabled['waveshare_audio']:
        args = {
            'use_sim_time': sim_time,
            'output_topic': topics.get('voice_text', '/voice/text'),
            'status_topic': topics.get('voice_status', '/waveshare_audio/status'),
            'transcript_json_topic': topics.get('voice_transcript', '/voice/transcript'),
        }
        _config_override(context, 'waveshare_audio', args)
        actions.append(_include(implementations, 'components', 'waveshare_audio', args))

    if enabled['localization']:
        args = {
            'use_sim_time': sim_time,
            'use_imu': as_launch_bool(enabled['imu']),
            'wheel_odometry_topic': topics.get('wheel_odometry', '/wheel/odometry'),
            'imu_topic': topics.get('imu_data', '/imu/data'),
            'filtered_odometry_topic': topics.get('odom', '/odom'),
            'map_frame': frames.get('map', 'map'),
            'odom_frame': frames.get('odom', 'odom'),
            'base_frame': frames.get('base', 'base_link'),
        }
        localization_config = LaunchConfiguration('localization_config_file').perform(context).strip()
        if localization_config:
            target = 'with_imu_config_file' if enabled['imu'] else 'wheel_only_config_file'
            args[target] = localization_config
        actions.append(_include(implementations, 'components', 'localization', args))

    return actions


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('profile', default_value='full'),
        DeclareLaunchArgument('profile_file', default_value=''),
        DeclareLaunchArgument('implementations_file', default_value=bringup_config_path('implementations.yaml')),
        DeclareLaunchArgument('robot_config_file', default_value=bringup_config_path('rover_v1.yaml')),
        DeclareLaunchArgument('topics_config_file', default_value=bringup_config_path('topics.yaml')),
        DeclareLaunchArgument('device_manager_config_file', default_value=''),
        DeclareLaunchArgument('twist_mux_config_file', default_value=bringup_config_path('core', 'twist_mux.yaml')),
        DeclareLaunchArgument('runtime_dir', default_value=''),
        DeclareLaunchArgument('device_config', default_value=''),
        DeclareLaunchArgument('discovery_mode', default_value=''),
        DeclareLaunchArgument('motor_device', default_value=''),
        DeclareLaunchArgument('imu_device', default_value=''),
        DeclareLaunchArgument('lidar_device', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('simulation', default_value='false'),
    ]
    for name in CORE_COMPONENTS:
        arguments.append(DeclareLaunchArgument(f'use_{name}', default_value=''))
        if name != 'twist_mux':
            arguments.append(DeclareLaunchArgument(f'{name}_config_file', default_value=''))
    return LaunchDescription([*arguments, OpaqueFunction(function=_launch_setup)])
