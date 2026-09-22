from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_imu', 'yahboom_imu_node', 'yahboom_imu_node', 'imu.yaml',
    )
