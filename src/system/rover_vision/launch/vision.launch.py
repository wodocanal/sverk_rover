from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _launch_setup(context, *, default_config):
    config_file = LaunchConfiguration('config_file').perform(context).strip()
    if not config_file or config_file == '.':
        config_file = default_config
    return [Node(
        package='rover_vision',
        executable='camera_detector_node',
        name='camera_detector_node',
        output='screen',
        additional_env={
            # Avoid user-site NumPy 2.x shadowing the distro NumPy used by
            # OpenCV on Raspberry Pi.
            'PYTHONNOUSERSITE': '1',
        },
        parameters=[config_file, {
            'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
            'input_topic': LaunchConfiguration('input_topic'),
            'processed_image_topic': LaunchConfiguration('processed_image_topic'),
            'processed_compressed_image_topic': LaunchConfiguration('processed_compressed_image_topic'),
            'detections_topic': LaunchConfiguration('detections_topic'),
            'frame_id': LaunchConfiguration('frame_id'),
        }],
    )]


def generate_launch_description():
    share = Path(get_package_share_directory('rover_vision'))
    default_config = str(share / 'config' / 'vision.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('variant', default_value='vision'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('input_topic', default_value='/image_raw'),
        DeclareLaunchArgument('processed_image_topic', default_value='/image_processed'),
        DeclareLaunchArgument('processed_compressed_image_topic', default_value='/image_processed/compressed'),
        DeclareLaunchArgument('detections_topic', default_value='/detections'),
        DeclareLaunchArgument('frame_id', default_value='camera_optical_frame'),
        OpaqueFunction(
            function=_launch_setup,
            kwargs={'default_config': default_config},
        ),
    ])
