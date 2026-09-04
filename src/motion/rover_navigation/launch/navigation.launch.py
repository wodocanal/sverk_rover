from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_share = Path(get_package_share_directory('rover_navigation'))
    description_share = Path(get_package_share_directory('rover_description'))

    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    bond_timeout = LaunchConfiguration('bond_timeout')
    default_params = str(pkg_share / 'config' / 'nav2.yaml')
    default_map = str(pkg_share / 'maps' / 'current' / 'map.yaml')
    # Included launch arguments share a context with their parent. Fall back
    # here as well as in DeclareLaunchArgument so an empty parent value cannot
    # accidentally erase the package default.
    params_file = PythonExpression([
        "'", LaunchConfiguration('params_file'), "' or '", default_params, "'",
    ])
    map_file = PythonExpression([
        "'", LaunchConfiguration('map'), "' or '", default_map, "'",
    ])
    use_rviz = LaunchConfiguration('use_rviz')
    rviz_config = LaunchConfiguration('rviz_config')

    common = [params_file, {
        'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
    }]

    localization_nodes = ['map_server', 'amcl']
    navigation_nodes = [
        'controller_server',
        'smoother_server',
        'planner_server',
        'behavior_server',
        'bt_navigator',
        'waypoint_follower',
    ]

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('variant', default_value='nav2'),
        DeclareLaunchArgument('autostart', default_value='true'),
        DeclareLaunchArgument('bond_timeout', default_value='4.0'),
        DeclareLaunchArgument(
            'params_file',
            default_value=default_params,
        ),
        DeclareLaunchArgument(
            'map',
            default_value=default_map,
        ),
        DeclareLaunchArgument('use_rviz', default_value='false'),
        DeclareLaunchArgument(
            'rviz_config',
            default_value=str(description_share / 'rviz' / 'display_navigation.rviz'),
        ),

        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[params_file, {
                'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
                'yaml_filename': map_file,
            }],
        ),
        Node(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            output='screen',
            parameters=common,
        ),
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_localization',
            output='screen',
            parameters=[{
                'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
                'autostart': ParameterValue(autostart, value_type=bool),
                'bond_timeout': ParameterValue(bond_timeout, value_type=float),
                'node_names': localization_nodes,
            }],
        ),

        Node(
            package='nav2_controller',
            executable='controller_server',
            name='controller_server',
            output='screen',
            parameters=common,
            remappings=[('cmd_vel', '/cmd_vel_nav')],
        ),
        Node(
            package='nav2_smoother',
            executable='smoother_server',
            name='smoother_server',
            output='screen',
            parameters=common,
        ),
        Node(
            package='nav2_planner',
            executable='planner_server',
            name='planner_server',
            output='screen',
            parameters=common,
        ),
        Node(
            package='nav2_behaviors',
            executable='behavior_server',
            name='behavior_server',
            output='screen',
            parameters=common,
            remappings=[('cmd_vel', '/cmd_vel_nav')],
        ),
        Node(
            package='nav2_bt_navigator',
            executable='bt_navigator',
            name='bt_navigator',
            output='screen',
            parameters=common,
        ),
        Node(
            package='nav2_waypoint_follower',
            executable='waypoint_follower',
            name='waypoint_follower',
            output='screen',
            parameters=common,
        ),
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_navigation',
            output='screen',
            parameters=[{
                'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
                'autostart': ParameterValue(autostart, value_type=bool),
                'bond_timeout': ParameterValue(bond_timeout, value_type=float),
                'node_names': navigation_nodes,
            }],
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rover_navigation_rviz',
            output='screen',
            arguments=['-d', rviz_config],
            parameters=[{
                'use_sim_time': ParameterValue(use_sim_time, value_type=bool),
            }],
            condition=IfCondition(use_rviz),
        ),
    ])
