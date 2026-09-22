"""Capture keeps advancing even if JPEG encoding cannot keep up."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from builtin_interfaces.msg import Time
from rover_camera.usb_camera_node import UsbCameraNode


def test_publish_uses_latest_frame_without_holding_capture_lock():
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
    UsbCameraNode._publish_latest_frame(node)
    UsbCameraNode._publish_latest_frame(node)
    UsbCameraNode._publish_latest_frame(node)
    assert frames[0] is first
    assert frames[1] is newest
    assert len(frames) == 2
    assert publisher.publish.call_count == 2
    assert publisher.publish.call_args_list[0].args[0].header.stamp.sec == 1
    assert publisher.publish.call_args_list[1].args[0].header.stamp.sec == 20
