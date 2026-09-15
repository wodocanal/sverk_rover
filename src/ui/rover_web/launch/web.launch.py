from pathlib import Path
import shutil

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rover_configuration import config_path, package_path, read_config
from rover_configuration.launch import parameter_override


ARGUMENTS = (
    'bind_address', 'port', 'command_topic', 'identity_file', 'rover_config_file',
    'plans_directory', 'hackathon_files_root', 'terminal_enabled', 'start_terminal',
    'terminal_url', 'terminal_bind_address', 'terminal_port', 'terminal_path',
    'terminal_workspace', 'rosboard_enabled', 'rosboard_port',
)


def launch_setup(context):
    share = Path(package_path('rover_web'))
    config = read_config(LaunchConfiguration('config_file').perform(context))
    parameters = dict(config['web_gateway_node']['ros__parameters'])
    launch_options = dict(config.get('launch', {}))
    workspace = str(share.parents[3])
    parameters.setdefault('identity_file', config_path('rover_description', 'rover_v1.yaml'))
    parameters.setdefault('rover_config_file', config_path('rover_description', 'rover_v1.yaml'))
    launch_options.setdefault('start_terminal', True)
    launch_options.setdefault('terminal_bind_address', '0.0.0.0')
    launch_options['terminal_workspace'] = launch_options.get('terminal_workspace') or workspace
    for name in ARGUMENTS:
        raw = LaunchConfiguration(name).perform(context)
        if raw.strip():
            target = launch_options if name in launch_options else parameters
            target[name] = parameter_override(raw, target.get(name, ''))

    actions = []
    if parameters.get('terminal_enabled', True) and launch_options['start_terminal']:
        ttyd_path = shutil.which('ttyd')
        if ttyd_path:
            actions.append(ExecuteProcess(
                cmd=[
                    ttyd_path, '-i', str(launch_options['terminal_bind_address']),
                    '-p', str(parameters.get('terminal_port', 7681)), '-W',
                    '/bin/bash', str(share / 'tools' / 'rover_terminal_shell.sh'),
                    str(Path(launch_options['terminal_workspace']).expanduser()),
                ],
                output='screen',
            ))
        elif not parameters.get('terminal_url'):
            parameters['terminal_enabled'] = False
            actions.append(LogInfo(msg='[WARN] ttyd not found; web terminal disabled.'))
        else:
            actions.append(LogInfo(msg='[WARN] ttyd not found; using terminal_url.'))
    parameters.update({
        'web_root': str(share / 'web'),
        'motion_executor_path': str(share / 'tools' / 'rover_motion_executor.py'),
        'seed_plans_directory': str(share / 'plans'),
    })
    actions.append(Node(
        package='rover_web', executable='web_gateway_node',
        name='web_gateway_node', output='screen',
        additional_env={'PYTHONNOUSERSITE': '1'},
        parameters=[parameters],
    ))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=config_path('rover_web', 'web.yaml')),
        *(DeclareLaunchArgument(name, default_value='') for name in ARGUMENTS),
        OpaqueFunction(function=launch_setup),
    ])
