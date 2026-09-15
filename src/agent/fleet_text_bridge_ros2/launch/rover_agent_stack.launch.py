from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from rover_configuration import config_path, package_path


def generate_launch_description():
    actions = []
    for argument, package, filename, launch_file in (
        ('agent_config_file', 'rover_agent_mcp', 'agent.yaml', 'agent_mcp.launch.py'),
        ('bridge_config_file', 'fleet_text_bridge_ros2', 'bridge.yaml', 'bridge.launch.py'),
    ):
        actions.append(DeclareLaunchArgument(argument, default_value=config_path(package, filename)))
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(package_path(package, 'launch', launch_file)),
            launch_arguments={'config_file': LaunchConfiguration(argument)}.items(),
        ))
    return LaunchDescription(actions)
