from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_wheel_odometry', 'wheel_odometry_node', 'wheel_odometry_node', 'odometry.yaml',
    )
