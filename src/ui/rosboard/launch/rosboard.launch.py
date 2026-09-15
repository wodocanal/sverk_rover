from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rosboard', 'rosboard_node', 'rosboard', 'rosboard.yaml',
        additional_env={'PYTHONNOUSERSITE': '1'},
    )
