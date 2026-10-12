import json
import struct
import time
from types import SimpleNamespace
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest
from rover_camera.media import Frame, MediaServer


def frame(sequence=1, captured=None):
    return Frame(b'original-jpeg', sequence, SimpleNamespace(sec=12, nanosec=34),
                 1280, 1024, time.monotonic() if captured is None else captured)


def test_latest_packet_and_matched_detections():
    latest = [frame()]
    server = MediaServer(lambda: latest[0], port=0)
    base = f'http://127.0.0.1:{server.server.server_port}'
    try:
        server.publish(latest[0], {'detections': [{'data': 'test'}]})
        latest[0] = frame(99)
        with urlopen(base + '/packet?mode=processed') as response:
            data = response.read()
        size = struct.unpack('!I', data[:4])[0]
        metadata = json.loads(data[4:4 + size])
        assert metadata['sequence'] == 1
        assert metadata['result']['detections'][0]['data'] == 'test'
        assert data[4 + size:] == b'original-jpeg'
        assert server.latest().sequence == 99
        server.clear()
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/packet?mode=processed')
        assert error.value.code == 503
        latest[0] = frame(captured=time.monotonic() - 10)
        assert server.latest() is None
    finally:
        server.close()


def test_unknown_resources_and_modes_are_rejected():
    server = MediaServer(lambda: frame(), port=0)
    try:
        for path, code in [('/file', 404), ('/packet?mode=invalid', 400)]:
            with pytest.raises(HTTPError) as error:
                urlopen(f'http://127.0.0.1:{server.server.server_port}{path}')
            assert error.value.code == code
    finally:
        server.close()
