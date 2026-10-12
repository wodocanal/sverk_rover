"""Capture keeps advancing even if JPEG encoding cannot keep up."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from builtin_interfaces.msg import Time
from rover_camera.usb_camera_node import UsbCameraNode


@pytest.mark.parametrize('passthrough', [False, True])
def test_publish_uses_latest_frame_without_holding_capture_lock(passthrough):
    first = np.zeros((2, 3, 3), dtype=np.uint8)
    newest = np.ones_like(first)
    publisher = Mock()
    publisher.get_subscription_count.return_value = 1
    node = SimpleNamespace(
        frame_lock=threading.RLock(), latest_frame_seq=1,
        latest_header_stamp=Time(sec=1), latest_width=3, latest_height=2,
        latest_frame=first, publish_raw=False, raw_publisher=None,
        publish_compressed=True, compressed_publisher=publisher,
        last_published_seq_raw=0, last_published_seq_compressed=0,
        frames_published_raw=0, frames_published_compressed=0, frame_id='camera',
    )
    frames = []

    def encode(frame):
        frames.append(frame)
        if len(frames) == 1:
            def capture():
                with node.frame_lock:
                    node.latest_frame = newest
                    node.latest_frame_seq = 20
                    node.latest_header_stamp = Time(sec=20)
            worker = threading.Thread(target=capture)
            worker.start()
            worker.join(timeout=1)
            assert not worker.is_alive(), 'JPEG encoding blocked capture'
        return b'jpeg'

    node._encode_frame = encode
    node._warn_throttled = Mock()
    if passthrough:
        node.latest_compressed = b'original camera JPEG'
        UsbCameraNode._publish_latest_frame(node)
        UsbCameraNode._publish_latest_frame(node)
        assert not frames
        assert publisher.publish.call_count == 1
        assert bytes(publisher.publish.call_args.args[0].data) == node.latest_compressed
        return
    UsbCameraNode._publish_latest_frame(node)
    UsbCameraNode._publish_latest_frame(node)
    UsbCameraNode._publish_latest_frame(node)
    assert frames[0] is first
    assert frames[1] is newest
    assert len(frames) == 2
    assert publisher.publish.call_count == 2
    assert publisher.publish.call_args_list[0].args[0].header.stamp.sec == 1
    assert publisher.publish.call_args_list[1].args[0].header.stamp.sec == 20


def test_capture_preserves_camera_jpeg_and_raw_pixels():
    import cv2

    frame = np.full((12, 16, 3), 120, dtype=np.uint8)
    _, jpeg = cv2.imencode('.jpg', frame)
    stop = threading.Event()
    capture = Mock()
    capture.isOpened.return_value = True

    def read():
        stop.set()
        return True, jpeg.reshape(1, -1)

    capture.read.side_effect = read
    node = SimpleNamespace(
        shutdown_event=stop, capture_lock=threading.RLock(),
        frame_lock=threading.RLock(), capture=capture, reconfigure_capture=False,
        rotate=0, latest_frame_seq=0, frames_captured=0,
        direct_video=False,
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time())),
        _request_reopen=Mock(), _warn_throttled=Mock(),
    )
    UsbCameraNode._capture_loop(node)
    assert node.latest_compressed == jpeg.tobytes()
    assert node.latest_frame.shape == (12, 16, 3)
    assert np.array_equal(node.latest_frame, cv2.imdecode(jpeg, cv2.IMREAD_COLOR))
    assert node.frames_captured == 1
