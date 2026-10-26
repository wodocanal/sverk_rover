"""Latest-frame HTTP transport. No ROS messages and no per-client JPEG encoding."""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import struct
import threading
import time
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    sequence: int
    stamp: object
    width: int
    height: int
    captured: float
    detections: dict | None = None

    def metadata(self):
        return {
            'sequence': self.sequence, 'width': self.width, 'height': self.height,
            'age_sec': max(0.0, time.monotonic() - self.captured),
            'stamp': {'sec': self.stamp.sec, 'nanosec': self.stamp.nanosec},
            'result': self.detections,
        }


def packet(frame):
    metadata = json.dumps(frame.metadata(), ensure_ascii=False).encode('utf-8')
    return struct.pack('!I', len(metadata)) + metadata + frame.jpeg


class MediaServer:
    def __init__(self, source, host='127.0.0.1', port=8091):
        self.source = source
        self.processed = None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                mode = query.get('mode', ['processed'])[0]
                if parsed.path not in ('/frame', '/packet', '/status', '/stream'):
                    self.send_error(404)
                    return
                if mode not in ('live', 'processed'):
                    self.send_error(400)
                    return
                try:
                    after = int(query.get('after', ['-1'])[0])
                except ValueError:
                    self.send_error(400, 'Invalid frame sequence')
                    return
                frame = owner.wait_for_new(mode, after) if after >= 0 else owner.latest(mode)
                if parsed.path == '/status':
                    body = json.dumps({'ok': True, 'mode': mode,
                                       'frame_ready': frame is not None,
                                       **(frame.metadata() if frame else {})}).encode()
                    return self.respond(body, 'application/json')
                if frame is None:
                    self.send_error(503, 'No fresh camera frame')
                    return
                try:
                    if parsed.path == '/stream':
                        self.connection.settimeout(2.0)
                        self.send_response(200)
                        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        sequence = -1
                        while not owner.stopped.is_set():
                            frame = owner.latest(mode)
                            if frame is None:
                                break
                            if frame.sequence != sequence:
                                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                                                 + str(len(frame.jpeg)).encode() + b'\r\n\r\n'
                                                 + frame.jpeg + b'\r\n')
                                self.wfile.flush()
                                sequence = frame.sequence
                            owner.stopped.wait(0.005)
                    elif parsed.path == '/packet':
                        self.respond(packet(frame), 'application/octet-stream')
                    else:
                        self.respond(frame.jpeg, 'image/jpeg')
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass

            def respond(self, body, content_type):
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def latest(self, mode='live'):
        if mode == 'processed':
            with self.lock:
                frame = self.processed
        else:
            frame = self.source()
        return frame if frame and time.monotonic() - frame.captured < 2.0 else None

    def wait_for_new(self, mode, sequence, timeout=1.0):
        deadline = time.monotonic() + timeout
        while not self.stopped.is_set():
            frame = self.latest(mode)
            if frame is None or frame.sequence != sequence:
                return frame
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return frame
            self.stopped.wait(min(0.01, remaining))
        return None

    def publish(self, frame, detections):
        with self.lock:
            self.processed = Frame(frame.jpeg, frame.sequence, frame.stamp,
                                   frame.width, frame.height, frame.captured, detections)

    def clear(self):
        with self.lock:
            self.processed = None

    def close(self):
        self.stopped.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
