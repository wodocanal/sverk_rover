"""Opt-in actual ROS messages from rover_vision's serializer, no hardware/LLM."""
import os
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.getenv('ROVER_AGENT_VISION_INTEGRATION') != '1', reason='opt-in isolated ROS test')
def test_vision_publisher_to_agent_tool():
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from rover_agent_mcp.ros_bridge import RoverRosBridge
    from rover_vision.camera_detector_node import CameraDetectorNode, Detection

    rclpy.init(args=['--ros-args', '-p', 'detections_topic:=/test/agent/detections'])
    agent = RoverRosBridge()
    sensor = Node('test_vision_publisher')
    pub = sensor.create_publisher(String, '/test/agent/detections', 10)
    serializer = SimpleNamespace(_detections_publisher=pub, frame_id='camera_optical_frame',
                                 model_name='custom-model', _model_manifest=None)
    mode = ['objects']

    def tick():
        stamp = sensor.get_clock().now().to_msg()
        if mode[0] == 'silent':
            return
        if mode[0] == 'stale':
            stamp.sec -= 30
        objects = [Detection(99, 'custom-object', 0.9, 10, 10, 30, 30)] if mode[0] == 'objects' else []
        CameraDetectorNode._publish_detections(serializer, objects, (480, 640, 3), stamp)

    sensor.create_timer(0.05, tick)
    executor = SingleThreadedExecutor()
    executor.add_node(agent)
    executor.add_node(sensor)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while agent.count_publishers('/test/agent/detections') == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        result = agent.call_tool('observe_detections', {'samples': 3, 'timeout_s': 3})
        assert result['success'], result
        assert result['confirmed'][0]['example']['label'] == 'custom-object'
        assert result['confirmed'][0]['frames_seen'] == 3
        assert result['publisher_count'] == 1
        mode[0] = 'empty'
        result = agent.call_tool('observe_detections', {'samples': 3, 'timeout_s': 3})
        assert result['success'] and result['state'] == 'empty', result
        mode[0] = 'stale'
        result = agent.call_tool('observe_detections', {'timeout_s': 0.3})
        assert not result['success'] and result['frames_received'] == 0, result
        mode[0] = 'silent'
        result = agent.call_tool('observe_detections', {'timeout_s': 0.3})
        assert not result['success'] and result['state'] == 'insufficient_frames', result
        second_pub = sensor.create_publisher(String, '/test/agent/detections', 10)
        try:
            deadline = time.monotonic() + 5
            while agent.count_publishers('/test/agent/detections') < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            mode[0] = 'objects'
            result = agent.call_tool('observe_detections', {'samples': 1, 'timeout_s': 3})
            assert not result['success'] and result['state'] == 'ambiguous_sources', result
        finally:
            sensor.destroy_publisher(second_pub)
            mode[0] = 'silent'
        sensor.destroy_publisher(pub)
        deadline = time.monotonic() + 5
        while agent.count_publishers('/test/agent/detections') and time.monotonic() < deadline:
            time.sleep(0.05)
        result = agent.call_tool('observe_detections', {'timeout_s': 0.3})
        assert not result['success'] and result['state'] == 'unavailable', result
    finally:
        executor.shutdown(timeout_sec=5)
        thread.join(timeout=5)
        agent.destroy_node()
        sensor.destroy_node()
        rclpy.shutdown()
