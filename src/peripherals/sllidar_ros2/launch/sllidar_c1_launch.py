from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'sllidar_ros2', 'sllidar_node', 'sllidar_node', 'lidar.yaml',
    )
