from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_led_strip', 'led_strip_node', 'led_strip_node', 'led_strip.yaml',
    )
