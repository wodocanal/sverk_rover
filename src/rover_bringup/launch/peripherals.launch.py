from pathlib import Path

import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def default_config_file() -> str:
    return str(Path(__file__).resolve().parents[1] / 'config' / 'peripherals.yaml')


def read_config(path: str) -> dict:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise FileNotFoundError(f'Peripheral config file not found: {config_path}')
    with config_path.open('r', encoding='utf-8') as stream:
        value = yaml.safe_load(stream)
    return value if isinstance(value, dict) else {}


def config_value(config: dict, keys: tuple[str, ...], default):
    value = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def launch_value(context, name: str, config: dict, keys: tuple[str, ...], default):
    override = LaunchConfiguration(name).perform(context).strip()
    if override:
        return override
    return config_value(config, keys, default)


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def as_int(value) -> int:
    return int(str(value).strip())


def as_float(value) -> float:
    return float(str(value).strip())


def launch_setup(context):
    config = read_config(LaunchConfiguration('config_file').perform(context))
    use_sim_time = as_bool(LaunchConfiguration('use_sim_time').perform(context))
    use_lidar = as_bool(
        launch_value(context, 'use_lidar', config, ('peripherals', 'use_lidar'), True)
    )
    use_camera = as_bool(
        launch_value(context, 'use_camera', config, ('peripherals', 'use_camera'), True)
    )
    use_vision = as_bool(
        launch_value(context, 'use_vision', config, ('peripherals', 'use_vision'), True)
    )
    use_led_strip = as_bool(
        launch_value(
            context, 'use_led_strip', config, ('peripherals', 'use_led_strip'), True
        )
    )
    use_octoliner = as_bool(
        launch_value(
            context, 'use_octoliner', config, ('peripherals', 'use_octoliner'), True
        )
    )
    use_voice = as_bool(
        launch_value(context, 'use_voice', config, ('peripherals', 'use_voice'), False)
    )

    actions = []
    lidar_config = dict(config.get('lidar', {}))
    camera_params = dict(config.get('camera', {}))
    vision_params = dict(config.get('vision', {}))
    led_strip_params = dict(config.get('led_strip', {}))
    octoliner_params = dict(config.get('octoliner', {}))
    voice_params = dict(config.get('voice', {}))

    if (
        use_led_strip
        and use_octoliner
        and str(led_strip_params.get('led_transport', 'auto')).strip().lower()
        in {'auto', 'spi'}
    ):
        actions.append(LogInfo(
            msg=(
                '[INFO] LED strip is configured for SPI transport. Make sure the data '
                'wire is connected to the SPI MOSI pin that matches spi_bus/spi_device.'
            )
        ))

    if use_lidar:
        lidar_params = {
            'channel_type': str(lidar_config.get('channel_type', 'serial')),
            'serial_port': str(launch_value(
                context,
                'lidar_device',
                config,
                ('lidar', 'serial_port'),
                '/tmp/rover_devices/lidar',
            )),
            'serial_baudrate': as_int(launch_value(
                context,
                'lidar_baudrate',
                config,
                ('lidar', 'serial_baudrate'),
                460800,
            )),
            'frame_id': str(launch_value(
                context,
                'lidar_frame_id',
                config,
                ('lidar', 'frame_id'),
                'lidar_link',
            )),
            'inverted': as_bool(launch_value(
                context,
                'lidar_inverted',
                config,
                ('lidar', 'inverted'),
                False,
            )),
            'angle_compensate': as_bool(launch_value(
                context,
                'lidar_angle_compensate',
                config,
                ('lidar', 'angle_compensate'),
                True,
            )),
            'scan_mode': str(launch_value(
                context,
                'lidar_scan_mode',
                config,
                ('lidar', 'scan_mode'),
                'Standard',
            )),
            'scan_frequency': as_float(launch_value(
                context,
                'lidar_scan_frequency',
                config,
                ('lidar', 'scan_frequency'),
                10.0,
            )),
            'range_min': as_float(launch_value(
                context,
                'lidar_range_min',
                config,
                ('lidar', 'range_min'),
                0.17,
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
        camera_params['use_sim_time'] = use_sim_time
        actions.append(Node(
            package='rover_camera',
            executable='usb_camera_node',
            name='usb_camera_node',
            output='screen',
            parameters=[camera_params],
        ))

    if use_camera and use_vision:
        vision_params.setdefault(
            'input_topic',
            str(camera_params.get('image_topic', '/image_raw')),
        )
        vision_params.setdefault(
            'frame_id',
            str(camera_params.get('frame_id', 'camera_optical_frame')),
        )
        vision_params['use_sim_time'] = use_sim_time
        actions.append(Node(
            package='rover_vision',
            executable='camera_detector_node',
            name='camera_detector_node',
            output='screen',
            parameters=[vision_params],
        ))

    if use_led_strip:
        led_strip_params['use_sim_time'] = use_sim_time
        actions.append(Node(
            package='rover_led_strip',
            executable='led_strip_node',
            name='led_strip_node',
            output='screen',
            parameters=[led_strip_params],
        ))

    if use_octoliner:
        octoliner_params['use_sim_time'] = use_sim_time
        actions.append(Node(
            package='rover_octoliner',
            executable='octoliner_node',
            name='octoliner_node',
            output='screen',
            parameters=[octoliner_params],
        ))

    if use_voice:
        actions.append(Node(
            package='rover_voice',
            executable='voice_module_node',
            name='voice_module_node',
            output='screen',
            parameters=[voice_params],
        ))

    return actions


def generate_launch_description():
    empty_default = ''
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config_file()),
        DeclareLaunchArgument('use_lidar', default_value=empty_default),
        DeclareLaunchArgument('use_camera', default_value=empty_default),
        DeclareLaunchArgument('use_vision', default_value=empty_default),
        DeclareLaunchArgument('use_led_strip', default_value=empty_default),
        DeclareLaunchArgument('use_octoliner', default_value=empty_default),
        DeclareLaunchArgument('use_voice', default_value=empty_default),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('lidar_device', default_value=empty_default),
        DeclareLaunchArgument('lidar_baudrate', default_value=empty_default),
        DeclareLaunchArgument('lidar_frame_id', default_value=empty_default),
        DeclareLaunchArgument('lidar_inverted', default_value=empty_default),
        DeclareLaunchArgument('lidar_angle_compensate', default_value=empty_default),
        DeclareLaunchArgument('lidar_scan_mode', default_value=empty_default),
        DeclareLaunchArgument('lidar_scan_frequency', default_value=empty_default),
        DeclareLaunchArgument('lidar_range_min', default_value=empty_default),
        OpaqueFunction(function=launch_setup),
    ])
