from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_web = LaunchConfiguration('use_web')
    use_display = LaunchConfiguration('use_display')
    use_rosboard = LaunchConfiguration('use_rosboard')

    return LaunchDescription([
        DeclareLaunchArgument('use_web', default_value='true'),
        DeclareLaunchArgument('use_display', default_value='true'),
        DeclareLaunchArgument('use_rosboard', default_value='true'),
        DeclareLaunchArgument('web_bind_address', default_value='0.0.0.0'),
        DeclareLaunchArgument('web_port', default_value='8765'),
        DeclareLaunchArgument('command_topic', default_value='/cmd_vel'),
        DeclareLaunchArgument('terminal_enabled', default_value='true'),
        DeclareLaunchArgument('start_terminal', default_value='true'),
        DeclareLaunchArgument('terminal_port', default_value='7681'),
        DeclareLaunchArgument('rosboard_port', default_value='8888'),
        DeclareLaunchArgument(
            'display_panel_mode',
            default_value='placeholder',
            description='Touchscreen right panel: placeholder or agent',
        ),
        DeclareLaunchArgument(
            'display_robot_serial',
            default_value='1',
            description='Touchscreen rover serial suffix',
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('rover_web'), 'launch', 'web.launch.py'
            ])),
            condition=IfCondition(use_web),
            launch_arguments={
                'bind_address': LaunchConfiguration('web_bind_address'),
                'port': LaunchConfiguration('web_port'),
                'command_topic': LaunchConfiguration('command_topic'),
                'terminal_enabled': LaunchConfiguration('terminal_enabled'),
                'start_terminal': LaunchConfiguration('start_terminal'),
                'terminal_port': LaunchConfiguration('terminal_port'),
                'rosboard_enabled': use_rosboard,
                'rosboard_port': LaunchConfiguration('rosboard_port'),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('rosboard'), 'launch', 'rosboard.launch.py'
            ])),
            condition=IfCondition(use_rosboard),
            launch_arguments={
                'port': LaunchConfiguration('rosboard_port'),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('rover_display'), 'launch', 'display.launch.py'
            ])),
            condition=IfCondition(use_display),
            launch_arguments={
                'right_panel_mode': LaunchConfiguration('display_panel_mode'),
                'robot_serial': LaunchConfiguration('display_robot_serial'),
            }.items(),
        ),
    ])
