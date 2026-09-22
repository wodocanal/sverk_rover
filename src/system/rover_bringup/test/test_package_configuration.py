"""Expand real ROS launch descriptions without executing hardware processes."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from launch_ros.actions import Node
from launch_ros.utilities import evaluate_parameters

from rover_bringup.configuration import load_component
from rover_configuration import config_path, node_parameters, package_path, read_config


def discover(**kwargs):
    return {name: SimpleNamespace(resolved_device='/dev/fake-' + name,
                                 baudrate=baud, parameters={})
            for name, baud in [('motor_controller', 115200), ('imu', 115200), ('lidar', 460800)]}


def expand(package, filename, overrides=None):
    context = LaunchContext()
    context.launch_configurations.update(overrides or {})
    source = PythonLaunchDescriptionSource(package_path(package, 'launch', filename))
    result = {}

    def text(ctx, value):
        return perform_substitutions(ctx, normalize_to_list_of_substitutions(value))

    def visit(actions, ctx):
        for action in actions:
            if action.condition is not None and not action.condition.evaluate(ctx):
                continue
            if isinstance(action, DeclareLaunchArgument):
                action.execute(ctx)
            elif isinstance(action, OpaqueFunction):
                visit(action.execute(ctx) or [], ctx)
            elif isinstance(action, IncludeLaunchDescription):
                child = LaunchContext()
                child.launch_configurations.update(ctx.launch_configurations)
                for key, value in action.launch_arguments:
                    child.launch_configurations[text(ctx, key)] = text(ctx, value)
                visit(action.launch_description_source.get_launch_description(child).entities, child)
            elif isinstance(action, TimerAction):
                visit(action.actions, ctx)
            elif isinstance(action, Node):
                name = text(ctx, action._Node__node_name)
                parameters = {}
                for item in evaluate_parameters(ctx, action._Node__parameters or []):
                    if isinstance(item, dict):
                        parameters.update(item)
                    elif isinstance(item, Path):
                        data = read_config(item)
                        parameters.update(data.get(name, {}).get('ros__parameters', {}))
                result[name] = parameters

    with patch('rover_device_manager.discovery.prepare_devices', side_effect=discover):
        visit(source.get_launch_description(context).entities, context)
    return result


class PackageLaunchTests(unittest.TestCase):
    def test_package_owned_configs_resolve(self):
        for name in ('base', 'odometry', 'imu', 'lidar', 'lidar_filter', 'camera',
                     'vision', 'led_strip', 'octoliner', 'audio', 'device_manager',
                     'agent', 'fleet_bridge'):
            with self.subTest(component=name):
                self.assertTrue(load_component('', name))

    def test_all_main_profiles_expand(self):
        for profile in ('full', 'hardware', 'minimal', 'mapping', 'navigation', 'agent'):
            with self.subTest(profile=profile):
                nodes = expand('rover_bringup', 'robot.launch.py', {'profile': profile})
                self.assertTrue(nodes)

    def test_full_profile_leaves_mapping_and_navigation_to_web(self):
        profile = read_config(config_path('rover_bringup', 'profiles/full.yaml'))
        self.assertFalse(profile['components']['nav2'])
        self.assertFalse(profile['components']['slam'])

    def test_main_and_standalone_use_same_calibration(self):
        main = expand('rover_bringup', 'robot.launch.py', {'profile': 'full'})
        for package, filename, name in (
            ('rover_base_driver', 'base.launch.py', 'base_driver_node'),
            ('rover_wheel_odometry', 'odometry.launch.py', 'wheel_odometry_node'),
            ('rover_imu', 'imu.launch.py', 'yahboom_imu_node'),
            ('rover_camera', 'camera.launch.py', 'usb_camera_node'),
            ('rover_led_strip', 'led_strip.launch.py', 'led_strip_node'),
            ('rover_vision', 'vision.launch.py', 'camera_detector_node'),
        ):
            with self.subTest(package=package):
                standalone = expand(package, filename)[name]
                combined = expand('rover_bringup', 'robot.launch.py', {
                    'profile': 'full', 'use_camera': 'true', 'use_vision': 'true',
                }) if name not in main else main
                for key, value in standalone.items():
                    self.assertEqual(combined[name][key], value, (name, key))

    def test_shared_geometry_and_encoders_are_typed(self):
        base = node_parameters(config_path('rover_base_driver', 'base.yaml'), 'base_driver_node')
        odom = node_parameters(config_path('rover_wheel_odometry', 'odometry.yaml'), 'wheel_odometry_node')
        for key in ('wheel_radius_m', 'wheelbase_m', 'track_width_m',
                    'encoder_lines', 'reduction_ratio', 'quadrature_factor'):
            self.assertEqual(base[key], odom[key])
            self.assertIsInstance(base[key], float)
        self.assertEqual(base['motor_command_order'], [3, 1, 2, 0])
        self.assertEqual(base['motor_command_signs'], [-1, -1, -1, -1])

    def test_web_service_does_not_load_ui_profile_as_node_params(self):
        nodes = expand('rover_bringup', 'ui.launch.py', {
            'use_web': 'true', 'use_display': 'false', 'use_rosboard': 'true',
            'start_terminal': 'false', 'web_port': '9876',
        })
        self.assertEqual(nodes['web_gateway_node']['port'], 9876)
        self.assertEqual(nodes['rosboard']['port'], 8888)
        self.assertNotIn('rover_status_display_node', nodes)

    def test_package_config_edit_and_cli_override(self):
        import tempfile
        import yaml

        params = node_parameters(config_path('rover_camera', 'camera.yaml'), 'usb_camera_node')
        params['fps'] = 12.0
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as stream:
            yaml.safe_dump({'usb_camera_node': {'ros__parameters': params}}, stream)
            stream.flush()
            nodes = expand('rover_camera', 'camera.launch.py', {'config_file': stream.name})
            self.assertEqual(nodes['usb_camera_node']['fps'], 12.0)
            nodes = expand('rover_camera', 'camera.launch.py', {
                'config_file': stream.name, 'fps': '20', 'rotate': '0',
            })
            self.assertEqual(nodes['usb_camera_node']['fps'], 20.0)
            self.assertEqual(nodes['usb_camera_node']['rotate'], 0)

    def test_web_yaml_settings_are_not_shadowed_by_launch_defaults(self):
        import tempfile
        import yaml

        config = read_config(config_path('rover_web', 'web.yaml'))
        config['web_gateway_node']['ros__parameters'].update({
            'port': 9877, 'command_topic': '/custom_cmd', 'terminal_enabled': False,
        })
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as stream:
            yaml.safe_dump(config, stream)
            stream.flush()
            nodes = expand('rover_bringup', 'ui.launch.py', {
                'web_config_file': stream.name, 'use_display': 'false', 'use_rosboard': 'false',
            })
            self.assertEqual(nodes['web_gateway_node']['port'], 9877)
            self.assertEqual(nodes['web_gateway_node']['command_topic'], '/custom_cmd')

    def test_other_standalone_launches_expand(self):
        for package, filename in (
            ('rover_waveshare_audio', 'waveshare_audio.launch.py'),
            ('rover_octoliner', 'octoliner.launch.py'),
            ('rover_lidar_filter', 'filter.launch.py'),
            ('sllidar_ros2', 'sllidar_c1_launch.py'),
            ('sllidar_ros2', 'view_sllidar_c1_launch.py'),
            ('rover_display', 'display.launch.py'),
            ('rover_description', 'description.launch.py'),
            ('rover_wheel_odometry', 'localization.launch.py'),
        ):
            with self.subTest(package=package):
                self.assertTrue(expand(package, filename))

    def test_agent_and_bridge_share_identity(self):
        nodes = expand('fleet_text_bridge_ros2', 'rover_agent_stack.launch.py')
        self.assertEqual(nodes['rover_agent_text_node']['robot_id'], nodes['fleet_text_bridge']['robot_id'])
        self.assertEqual(nodes['rover_mcp_server']['mcp_port'], 8766)
        self.assertEqual(nodes['rover_agent_text_node']['mcp_url'], 'http://127.0.0.1:8766/mcp')

    def test_navigation_wrappers_expand(self):
        for filename in ('navigation.launch.py', 'mapping.launch.py', 'update_map.launch.py'):
            with self.subTest(filename=filename):
                self.assertTrue(expand('rover_bringup', filename))


if __name__ == '__main__':
    unittest.main()
