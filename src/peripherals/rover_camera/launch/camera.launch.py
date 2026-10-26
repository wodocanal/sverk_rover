"""Launch the direct camera pipeline with the package-owned vision defaults."""

import json

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_configuration import config_path, node_parameters, read_config
from rover_configuration.launch import parameter_override


def generate_launch_description():
    camera_file = config_path('rover_camera', 'camera.yaml')
    camera_defaults = node_parameters(camera_file, 'usb_camera_node')
    camera_defaults.setdefault('use_sim_time', False)

    def setup(context):
        parameters = node_parameters(
            LaunchConfiguration('config_file').perform(context),
            'usb_camera_node',
        )
        for name, default in camera_defaults.items():
            raw = LaunchConfiguration(name).perform(context)
            if raw.strip():
                parameters[name] = parameter_override(
                    raw, parameters.get(name, default)
                )
        parameters.setdefault('use_sim_time', False)

        # The detector lives inside usb_camera_node for direct video, so the
        # standalone launch supplies the same defaults as rover_bringup.
        vision = node_parameters(
            config_path('rover_vision', 'vision.yaml'),
            'camera_detector_node',
        )
        topics = read_config(config_path('rover_interfaces', 'topics.yaml')).get(
            'topics', {}
        )
        vision['frame_id'] = parameters['frame_id']
        vision['detections_topic'] = topics.get('detections', '/detections')
        vision['qr_detections_topic'] = topics.get(
            'qr_detections', '/qr_detections'
        )
        vision['use_sim_time'] = parameters['use_sim_time']
        parameters['vision_parameters_json'] = json.dumps(vision)

        return [Node(
            package='rover_camera',
            executable='usb_camera_node',
            name='usb_camera_node',
            output='screen',
            parameters=[parameters],
            additional_env={'PYTHONNOUSERSITE': '1'},
        )]

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=camera_file),
        *(DeclareLaunchArgument(name, default_value='') for name in camera_defaults),
        OpaqueFunction(function=setup),
    ])
