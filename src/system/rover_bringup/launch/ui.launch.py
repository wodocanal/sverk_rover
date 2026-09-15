from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from rover_bringup.configuration import as_bool, bringup_config_path, read_yaml_file
from rover_configuration import config_path, package_path

# Translate the old aggregate UI arguments without inventing parameter defaults.
WEB_ARGUMENTS = {
    'web_config_file': ('config_file', 'web', 'config_file'),
    'web_bind_address': ('bind_address', 'web', 'bind_address'),
    'web_port': ('port', 'web', 'port'),
    'command_topic': ('command_topic', 'web', 'command_topic'),
    'identity_file': ('identity_file', 'web', 'identity_file'),
    'rover_config_file': ('rover_config_file', 'web', 'rover_config_file'),
    'plans_directory': ('plans_directory', 'web', 'plans_directory'),
    'hackathon_files_root': ('hackathon_files_root', 'web', 'hackathon_files_root'),
    'terminal_enabled': ('terminal_enabled', 'terminal', 'enabled'),
    'start_terminal': ('start_terminal', 'terminal', 'start'),
    'terminal_bind_address': ('terminal_bind_address', 'terminal', 'bind_address'),
    'terminal_port': ('terminal_port', 'terminal', 'port'),
    'terminal_path': ('terminal_path', 'terminal', 'path'),
    'terminal_url': ('terminal_url', 'terminal', 'url'),
    'terminal_workspace': ('terminal_workspace', 'terminal', 'workspace'),
    'rosboard_port': ('rosboard_port', 'rosboard', 'port'),
}
DISPLAY_ARGUMENTS = {
    'display_config_file': ('config_file', 'display', 'config_file'),
    'display_panel_mode': ('right_panel_mode', 'display', 'panel_mode'),
    'display_robot_serial': ('robot_serial', 'display', 'robot_serial'),
    'display_agent_text_topic': ('agent_text_topic', 'display', 'agent_text_topic'),
    'display_battery_topic': ('battery_topic', 'display', 'battery_topic'),
}


def launch_text(value):
    return str(value).lower() if isinstance(value, bool) else str(value)


def overrides(context, config, mapping):
    result = {}
    for argument, (target, section, key) in mapping.items():
        value = LaunchConfiguration(argument).perform(context).strip()
        if not value:
            value = config.get(section, {}).get(key)
        if value is not None and str(value).strip():
            result[target] = launch_text(value)
    return result


def include(package, filename, arguments):
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(package_path(package, 'launch', filename)),
        launch_arguments=arguments.items(),
    )


def launch_setup(context):
    filename = LaunchConfiguration('config_file').perform(context).strip()
    config = read_yaml_file(filename) if filename else {}
    enabled = {}
    for name in ('web', 'display', 'rosboard'):
        raw = LaunchConfiguration('use_' + name).perform(context).strip()
        enabled[name] = as_bool(raw if raw else config.get('ui', {}).get('use_' + name, True))
    actions = []
    web = overrides(context, config, WEB_ARGUMENTS)
    if enabled['web']:
        web.setdefault('config_file', config_path('rover_web', 'web.yaml'))
        web['rosboard_enabled'] = launch_text(enabled['rosboard'])
        actions.append(include('rover_web', 'web.launch.py', web))
    if enabled['rosboard']:
        args = {'port': web['rosboard_port']} if 'rosboard_port' in web else {}
        args['config_file'] = config_path('rosboard', 'rosboard.yaml')
        actions.append(include('rosboard', 'rosboard.launch.py', args))
    if enabled['display']:
        display = overrides(context, config, DISPLAY_ARGUMENTS)
        display.setdefault('config_file', config_path('rover_display', 'display.yaml'))
        actions.append(include(
            'rover_display', 'display.launch.py',
            display,
        ))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=bringup_config_path('profiles', 'ui.yaml')),
        *(DeclareLaunchArgument('use_' + name, default_value='')
          for name in ('web', 'display', 'rosboard')),
        *(DeclareLaunchArgument(name, default_value='')
          for name in dict.fromkeys([*WEB_ARGUMENTS, *DISPLAY_ARGUMENTS])),
        OpaqueFunction(function=launch_setup),
    ])
