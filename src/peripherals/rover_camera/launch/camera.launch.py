from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_camera', 'usb_camera_node', 'usb_camera_node', 'camera.yaml',
        additional_env={'PYTHONNOUSERSITE': '1'},
    )
