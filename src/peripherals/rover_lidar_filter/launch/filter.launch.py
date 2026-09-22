from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_lidar_filter', 'lidar_footprint_filter', 'lidar_footprint_filter', 'default.yaml',
    )
