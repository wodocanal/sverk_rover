import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import CompressedImage

from rover_web.web_gateway_node import RoverWebGateway


def test_compressed_watch_keeps_latest_frame_and_requests_depth_one():
    node = SimpleNamespace(
        _lock=threading.RLock(), _image_watches={}, create_subscription=Mock(),
    )
    watch = RoverWebGateway._ensure_image_watch(
        node, '/image_raw/compressed', 'sensor_msgs/msg/CompressedImage',
    )
    _, _, callback, qos = node.create_subscription.call_args.args
    assert qos.depth == 1
    assert qos.reliability == ReliabilityPolicy.BEST_EFFORT
    for data in (b'old', b'new'):
        callback(CompressedImage(format='jpeg', data=data))
    assert watch.frame_bytes == b'new'
    assert watch.message_count == 2


def test_snapshot_rejects_stale_frame():
    watch = SimpleNamespace(
        frame_bytes=b'jpeg', content_type='image/jpeg',
        last_updated_monotonic=time.monotonic(),
    )
    node = SimpleNamespace(
        _lock=threading.RLock(),
        _resolve_topic_type=lambda *_: ('sensor_msgs/msg/CompressedImage', []),
        _ensure_image_watch=lambda *_: watch,
    )
    assert RoverWebGateway.camera_frame(node, '/camera') == (b'jpeg', 'image/jpeg')
    watch.last_updated_monotonic -= 3
    with pytest.raises(RuntimeError, match='stale'):
        RoverWebGateway.camera_frame(node, '/camera')
