from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_vision', 'camera_detector_node', 'camera_detector_node', 'vision.yaml',
        additional_env={'PYTHONNOUSERSITE': '1'},
    )
