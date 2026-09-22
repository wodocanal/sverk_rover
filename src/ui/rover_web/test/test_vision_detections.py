import json
import threading
import time
from types import SimpleNamespace

from std_msgs.msg import String

from rover_web.web_gateway_node import RoverWebGateway


def test_vision_detections_decodes_latest_json_message():
    message = String()
    message.data = json.dumps({
        'count': 1,
        'detections': [{'label': 'left', 'confidence': 0.9, 'bbox': {'x': 1}}],
    })
    watch = SimpleNamespace(
        raw_message=message,
        message_count=4,
        last_updated_monotonic=time.monotonic(),
        last_error=None,
    )
    node = SimpleNamespace(
        _lock=threading.RLock(),
        _vision_parameter_values=lambda: {'detections_topic': '/detections'},
        _ensure_topic_watch=lambda topic, type_name: watch,
    )
    payload = RoverWebGateway.vision_detections(node)
    assert payload['topic'] == '/detections'
    assert payload['message_count'] == 4
    assert payload['result']['detections'][0]['label'] == 'left'


def test_vision_detections_reports_invalid_message():
    watch = SimpleNamespace(
        raw_message=String(data='not json'), message_count=1,
        last_updated_monotonic=time.monotonic(), last_error=None,
    )
    node = SimpleNamespace(
        _lock=threading.RLock(),
        _vision_parameter_values=lambda: {},
        _ensure_topic_watch=lambda topic, type_name: watch,
    )
    payload = RoverWebGateway.vision_detections(node)
    assert payload['result'] is None
    assert 'JSON' in payload['last_error']
