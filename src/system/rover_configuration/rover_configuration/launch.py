"""Small launcher for a single node with package-owned YAML defaults."""

import yaml

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_configuration import config_path, node_parameters


def parameter_override(raw: str, default):
    if isinstance(default, str):
        return raw
    value = yaml.safe_load(raw)
    if isinstance(default, bool) and not isinstance(value, bool):
        raise ValueError(f'Expected a boolean, got {raw!r}')
    if isinstance(default, list) and not isinstance(value, list):
        raise ValueError(f'Expected a list, got {raw!r}')
    if isinstance(default, float):
        return float(value)
    if isinstance(default, int) and not isinstance(default, bool):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f'Expected an integer, got {raw!r}')
    return value


def node_launch(package, executable, node_name, filename, *, additional_env=None):
    default_file = config_path(package, filename)
    defaults = node_parameters(default_file, node_name)
    defaults.setdefault('use_sim_time', False)

    def setup(context):
        parameters = node_parameters(
            LaunchConfiguration('config_file').perform(context), node_name,
        )
        for name, default in defaults.items():
            raw = LaunchConfiguration(name).perform(context)
            if raw.strip():
                parameters[name] = parameter_override(raw, parameters.get(name, default))
        return [Node(
            package=package, executable=executable, name=node_name, output='screen',
            parameters=[parameters], additional_env=additional_env or {},
        )]

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_file),
        *(DeclareLaunchArgument(name, default_value='') for name in defaults),
        OpaqueFunction(function=setup),
    ])
