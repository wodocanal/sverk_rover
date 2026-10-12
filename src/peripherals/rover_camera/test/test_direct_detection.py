"""Exercise direct JPEG -> QR -> ROS results and matched HTTP image without image topics."""
import json
import time

import cv2
import numpy as np
import rclpy
from rclpy.parameter import Parameter
from rover_camera.media import Frame, MediaServer
from rover_vision.camera_detector_node import CameraDetectorNode


def test_direct_qr_keeps_original_jpeg_and_processes_each_frame_once():
    rclpy.init()
    latest = [None]
    media = MediaServer(lambda: latest[0], port=0)
    node = None
    try:
        node = CameraDetectorNode(frame_source=media.latest, result_sink=media,
            parameter_overrides=[Parameter('enabled', value=True),
                                 Parameter('detect_objects', value=False),
                                 Parameter('detect_qr', value=True)])
        qr = cv2.QRCodeEncoder_create().encode('rover-direct-qr')
        qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        qr = cv2.resize(qr, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
        _, encoded = cv2.imencode('.jpg', qr)
        jpeg = encoded.tobytes()
        stamp = node.get_clock().now().to_msg()
        latest[0] = Frame(jpeg, 1, stamp, qr.shape[1], qr.shape[0], time.monotonic())
        node._process_latest_frame()
        result = media.latest('processed')
        assert result.jpeg is jpeg
        assert result.sequence == 1
        assert any(d.get('data') == 'rover-direct-qr' for d in result.detections['detections'])
        assert node._subscription is None
        assert node._raw_publisher is None and node._compressed_publisher is None
        node._process_latest_frame()
        assert node._frames_processed == 1
        response = node.set_parameters_atomically([Parameter('enabled', value=False)])
        assert response.successful and media.latest('processed') is None
    finally:
        media.close()
        if node:
            node.close()
            node.destroy_node()
        rclpy.shutdown()
