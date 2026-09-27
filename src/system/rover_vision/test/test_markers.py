import json
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from rover_vision import markers as marker_module
from rover_vision.markers import MarkerDetector
from rover_vision.camera_detector_node import CameraDetectorNode, Detection


DENSE_QR_TEXT = (
    'Состояние: тяжелое \r\n'
    'Сознание: в сознании \r\n'
    'Дыхание: затрудненное \r\n'
    'Пульс: 118 уд/мин \r\n'
    'Требуется: неотложная медицинская помощь'
)


def marker_scene():
    scene = np.full((440, 800, 3), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, 'generateImageMarker'):
        aruco = cv2.aruco.generateImageMarker(dictionary, 17, 180)
    else:
        aruco = cv2.aruco.drawMarker(dictionary, 17, 180)
    scene[80:260, 60:240] = cv2.cvtColor(aruco, cv2.COLOR_GRAY2BGR)
    qr = cv2.QRCodeEncoder_create().encode('rover-test-qr')
    qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    qr = cv2.resize(qr, None, fx=7, fy=7, interpolation=cv2.INTER_NEAREST)
    height, width = qr.shape
    scene[60:60+height, 390:390+width] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
    return scene


def dense_qr_scene():
    """Reproduce a dense, slightly blurred QR as seen by the rover camera."""
    qr = cv2.QRCodeEncoder_create().encode(DENSE_QR_TEXT)
    qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    qr = cv2.resize(qr, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    qr = cv2.GaussianBlur(qr, (5, 5), 0)
    height, width = qr.shape
    scene = np.full((440, 800, 3), 255, np.uint8)
    scene[80:80+height, 390:390+width] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
    return scene


@pytest.mark.parametrize('aruco,qr', [(False,False),(True,False),(False,True),(True,True)])
def test_real_opencv_marker_detection_and_switches(aruco, qr):
    frame = marker_scene()
    detector = MarkerDetector(aruco=aruco, qr=qr)
    markers = detector.detect(frame)
    assert sum(item['kind'] == 'aruco' for item in markers) == int(aruco)
    assert sum(item['kind'] == 'qr' for item in markers) == int(qr)
    for marker in markers:
        assert len(marker['corners']) == 4
        assert 'confidence' not in marker
        if marker['kind'] == 'aruco':
            assert marker['marker_id'] == 17
            assert marker['dictionary'] == 'DICT_4X4_50'
        else:
            assert marker['data'] == 'rover-test-qr' and marker['decoded']
    annotated = detector.annotate(frame.copy(), markers)
    assert bool(np.any(annotated != frame)) == (aruco or qr)


def test_wrong_dictionary_and_empty_scene():
    assert MarkerDetector(aruco=True, dictionary='DICT_5X5_50').detect(marker_scene()) == []
    assert MarkerDetector(aruco=True, qr=True).detect(np.full((400,400,3),255,np.uint8)) == []
    with pytest.raises(ValueError):
        MarkerDetector(dictionary='invalid')


@pytest.mark.skipif(marker_module.zxingcpp is None, reason='zxing-cpp is not installed')
def test_dense_qr_uses_fallback_when_opencv_only_detects_its_outline():
    markers = MarkerDetector(qr=True).detect(dense_qr_scene())
    decoded = [item['data'] for item in markers if item['kind'] == 'qr' and item['decoded']]
    assert decoded == [DENSE_QR_TEXT]


def test_markers_and_objects_share_detection_topic():
    node = SimpleNamespace(_detections_publisher=Mock(), frame_id='camera_optical_frame',
                           model_name='yolo11n', _model_manifest=None)
    markers = MarkerDetector(aruco=True, qr=True).detect(marker_scene())
    CameraDetectorNode._publish_detections(node, [Detection(0,'person',.9,0,0,30,40)],
                                          (440,800,3), None, markers=markers)
    payload = json.loads(node._detections_publisher.publish.call_args.args[0].data)
    assert payload['count'] == 3
    assert payload['object_count'] == 1 and payload['marker_count'] == 2
    assert {item['kind'] for item in payload['detections']} == {'object','aruco','qr'}
