from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_base_driver', 'base_driver_node', 'base_driver_node', 'base.yaml',
    )
