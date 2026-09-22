from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_display', 'status_display_node', 'rover_status_display_node', 'display.yaml',
    )
