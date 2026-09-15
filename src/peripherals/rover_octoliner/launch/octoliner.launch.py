from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_octoliner', 'octoliner_node', 'octoliner_node', 'octoliner.yaml',
    )
