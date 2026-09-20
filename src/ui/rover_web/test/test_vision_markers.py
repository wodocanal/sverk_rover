"""Optional full HTTP/ROS/video test using the bundled weights, no robot hardware."""
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2
import numpy as np
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, CompressedImage

from rover_vision.camera_detector_node import CameraDetectorNode
from rover_web.web_gateway_node import RoverWebGateway


def test_real_model_and_marker_controls(tmp_path):
    pytest.importorskip('ultralytics')
    import torch
    torch.set_num_threads(2)
    rclpy.init(args=['--ros-args', '-p', 'port:=0',
        '-p', f'hackathon_files_root:={tmp_path}/files', '-p', f'plans_directory:={tmp_path}/plans'])
    executor = SingleThreadedExecutor()
    vision = web = camera = worker = None
    try:
        vision, web, camera = CameraDetectorNode(), RoverWebGateway(), Node('test_camera')
        publisher = camera.create_publisher(Image, '/image_raw', qos_profile_sensor_data)
        output = []
        camera.create_subscription(CompressedImage, '/image_processed/compressed',
                                   lambda msg: output.append(msg), qos_profile_sensor_data)
        for node in (vision, web, camera):
            executor.add_node(node)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        root = f'http://127.0.0.1:{web._http_server.server_port}'

        def api(path, data=None):
            request = Request(root+path, data=json.dumps(data).encode() if data is not None else None,
                              headers={'Content-Type':'application/json'})
            with urlopen(request, timeout=30) as response:
                return json.load(response)

        settings = api('/api/vision/settings')
        assert settings['selected_model']['id'] == 'yolo11n'
        with pytest.raises(HTTPError):
            api('/api/vision/settings', {'aruco_dictionary':'invalid'})
        assert vision.aruco_dictionary == 'DICT_4X4_50'
        api('/api/vision/settings', {'detect_aruco':True, 'detect_qr':True, 'aruco_dictionary':'DICT_4X4_50'})
        api('/api/vision/settings', {'enabled':True})
        assert vision._active
        frame = np.full((440,800,3),255,np.uint8)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        aruco = cv2.aruco.generateImageMarker(dictionary,17,180) if hasattr(cv2.aruco,'generateImageMarker') \
            else cv2.aruco.drawMarker(dictionary,17,180)
        frame[80:260,60:240] = cv2.cvtColor(aruco,cv2.COLOR_GRAY2BGR)
        qr = cv2.QRCodeEncoder_create().encode('rover-test-qr')
        qr = cv2.copyMakeBorder(qr,4,4,4,4,cv2.BORDER_CONSTANT,value=255)
        qr = cv2.resize(qr,None,fx=7,fy=7,interpolation=cv2.INTER_NEAREST)
        frame[60:60+qr.shape[0],390:390+qr.shape[1]] = cv2.cvtColor(qr,cv2.COLOR_GRAY2BGR)
        message = Image(height=440,width=800,encoding='bgr8',step=2400,data=frame.tobytes())
        api('/api/vision/detections')  # Register the web's lazy subscription before publishing.
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            publisher.publish(message)
            time.sleep(.3)
            result = api('/api/vision/detections').get('result')
            if result and result['marker_count'] == 2 and output:
                break
        assert result['marker_count'] == 2
        assert result['model']['id'] == 'yolo11n'
        assert any(item.get('data') == 'rover-test-qr' for item in result['detections'])
        assert any(item.get('marker_id') == 17 for item in result['detections'])
        processed = cv2.imdecode(np.frombuffer(bytes(output[-1].data),np.uint8),cv2.IMREAD_COLOR)
        assert processed.shape == frame.shape and np.any(processed != frame)
        with pytest.raises(HTTPError) as error:
            api('/api/vision/settings', {'detect_qr':False})
        assert error.value.code == 400
        api('/api/vision/settings', {'enabled':False})
        api('/api/vision/settings', {'detect_qr':False, 'detect_aruco':False})
        assert not vision.detect_qr and not vision.detect_aruco
    finally:
        executor.shutdown(timeout_sec=3)
        if worker:
            worker.join(timeout=3)
        for node in (vision,web,camera):
            if node:
                node.destroy_node()
        rclpy.shutdown()
