from rover_configuration.launch import node_launch


def generate_launch_description():
    return node_launch(
        'rover_waveshare_audio', 'waveshare_audio_node', 'waveshare_audio_node', 'audio.yaml',
    )
