#!/usr/bin/env python3
"""Web gateway for rover status, ROS inspection, camera preview and drive."""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ament_index_python.packages import get_package_share_directory
import cv2
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from rosidl_runtime_py.utilities import get_message, get_service
from sensor_msgs.msg import CompressedImage, Image, Imu
import yaml


MAX_REQUEST_BYTES = 1_000_000
IMAGE_TOPIC_TYPES = {
    'sensor_msgs/msg/Image',
    'sensor_msgs/msg/CompressedImage',
}
PLAN_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def current_ipv4_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        output = subprocess.run(
            ['hostname', '-I'],
            check=False,
            capture_output=True,
            text=True,
            timeout=0.5,
        ).stdout
        for candidate in output.split():
            if ':' not in candidate and not candidate.startswith('127.'):
                addresses.append(candidate)
    except (OSError, subprocess.SubprocessError):
        pass
    return list(dict.fromkeys(addresses))


def age_seconds(monotonic_timestamp: float) -> float | None:
    if monotonic_timestamp <= 0.0:
        return None
    return max(0.0, time.monotonic() - monotonic_timestamp)


def normalize_topic_name(name: str) -> str:
    text = name.strip()
    if not text:
        raise ValueError('Topic name is required')
    return text if text.startswith('/') else f'/{text}'


def normalize_service_name(name: str) -> str:
    text = name.strip()
    if not text:
        raise ValueError('Service name is required')
    return text if text.startswith('/') else f'/{text}'


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def sanitize_payload(value: Any, *, depth: int = 0, max_items: int = 64) -> Any:
    if depth > 8:
        return '...'

    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value

    if isinstance(value, (bytes, bytearray, memoryview)):
        return f'<{len(value)} bytes>'

    if isinstance(value, array):
        return sanitize_payload(list(value), depth=depth + 1, max_items=max_items)

    if isinstance(value, dict):
        items = list(value.items())
        output = {
            str(key): sanitize_payload(item, depth=depth + 1, max_items=max_items)
            for key, item in items[:max_items]
        }
        if len(items) > max_items:
            output['__truncated__'] = f'{len(items) - max_items} more fields'
        return output

    if isinstance(value, (list, tuple)):
        items = [
            sanitize_payload(item, depth=depth + 1, max_items=max_items)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append(f'... {len(value) - max_items} more items')
        return items

    if hasattr(value, 'tolist'):
        return sanitize_payload(value.tolist(), depth=depth + 1, max_items=max_items)

    return str(value)


def make_message_template(message_type: type[Any]) -> dict[str, Any]:
    return sanitize_payload(message_to_ordereddict(message_type()), max_items=24)


def compressed_content_type(format_text: str) -> str:
    lowered = format_text.lower()
    if 'png' in lowered:
        return 'image/png'
    return 'image/jpeg'


def read_yaml(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else fallback
    except (OSError, yaml.YAMLError):
        return fallback


def quaternion_yaw(message: Odometry) -> float:
    q = message.pose.pose.orientation
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


@dataclass
class TopicSnapshot:
    received_monotonic: float = 0.0
    message_count: int = 0


@dataclass
class TopicWatch:
    topic: str
    type_name: str
    msg_class: type[Any]
    subscription: Any
    last_message: Any = None
    last_updated_monotonic: float = 0.0
    message_count: int = 0
    last_error: str | None = None
    last_access_monotonic: float = 0.0


@dataclass
class ImageWatch:
    topic: str
    type_name: str
    subscription: Any
    frame_bytes: bytes | None = None
    content_type: str = 'image/jpeg'
    width: int = 0
    height: int = 0
    encoding: str = ''
    message_count: int = 0
    last_updated_monotonic: float = 0.0
    last_error: str | None = None
    last_access_monotonic: float = 0.0


@dataclass
class PublisherHandle:
    topic: str
    type_name: str
    msg_class: type[Any]
    publisher: Any


@dataclass
class ServiceHandle:
    service: str
    type_name: str
    srv_class: type[Any]
    client: Any


class RoverWebGateway(Node):
    def __init__(self) -> None:
        super().__init__('web_gateway_node')

        share = Path(get_package_share_directory('rover_web'))
        try:
            rover_share = Path(get_package_share_directory('rover_bringup'))
        except Exception:
            rover_share = share
        home = Path.home()

        self.declare_parameter('bind_address', '0.0.0.0')
        self.declare_parameter('port', 8765)
        self.declare_parameter(
            'identity_file',
            str(share / 'config' / 'robot_identity.yaml'),
        )
        self.declare_parameter(
            'rover_config_file',
            str(rover_share / 'config' / 'rover.yaml'),
        )
        self.declare_parameter('web_root', str(share / 'web'))
        self.declare_parameter(
            'motion_executor_path',
            str(share / 'tools' / 'rover_motion_executor.py'),
        )
        self.declare_parameter(
            'plans_directory',
            str(home / '.local' / 'share' / 'sverh-rover-web' / 'plans'),
        )
        self.declare_parameter(
            'seed_plans_directory',
            str(share / 'plans'),
        )
        self.declare_parameter('command_topic', '/cmd_vel')
        self.declare_parameter('terminal_enabled', False)
        self.declare_parameter('terminal_url', '')
        self.declare_parameter('terminal_port', 7681)
        self.declare_parameter('terminal_path', '/terminal/')
        self.declare_parameter('drive_command_timeout_sec', 0.25)
        self.declare_parameter('default_linear_speed_mps', 0.18)
        self.declare_parameter('default_lateral_speed_mps', 0.16)
        self.declare_parameter('default_angular_speed_radps', 0.70)
        self.declare_parameter('max_linear_speed_mps', 0.35)
        self.declare_parameter('max_lateral_speed_mps', 0.35)
        self.declare_parameter('max_angular_speed_radps', 1.50)
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter('wheel_odom_topic', '/wheel/odometry')
        self.declare_parameter('imu_topic', '/imu/data')
        self.declare_parameter('diagnostics_topic', '/diagnostics')
        self.declare_parameter('runtime_dir', '/tmp/rover_devices')
        self.declare_parameter('activity_limit', 1000)
        self.declare_parameter('stop_hold_sec', 0.75)

        self.bind_address = str(self.get_parameter('bind_address').value)
        self.port = int(self.get_parameter('port').value)
        self.identity_path = Path(
            str(self.get_parameter('identity_file').value)
        ).expanduser()
        self.rover_config_path = Path(
            str(self.get_parameter('rover_config_file').value)
        ).expanduser()
        self.web_root = Path(
            str(self.get_parameter('web_root').value)
        ).expanduser().resolve()
        self.executor_path = Path(
            str(self.get_parameter('motion_executor_path').value)
        ).expanduser()
        self.plans_directory = Path(
            str(self.get_parameter('plans_directory').value)
        ).expanduser()
        self.seed_plans_directory = Path(
            str(self.get_parameter('seed_plans_directory').value)
        ).expanduser()
        self.command_topic = str(self.get_parameter('command_topic').value)
        self.terminal_enabled = bool(self.get_parameter('terminal_enabled').value)
        self.terminal_url = str(self.get_parameter('terminal_url').value).strip()
        self.terminal_port = int(self.get_parameter('terminal_port').value)
        self.terminal_path = (
            str(self.get_parameter('terminal_path').value).strip() or '/terminal/'
        )
        self.drive_command_timeout_sec = max(
            0.1, float(self.get_parameter('drive_command_timeout_sec').value)
        )
        self.default_linear_speed = max(
            0.05, float(self.get_parameter('default_linear_speed_mps').value)
        )
        self.default_lateral_speed = max(
            0.05, float(self.get_parameter('default_lateral_speed_mps').value)
        )
        self.default_angular_speed = max(
            0.05, float(self.get_parameter('default_angular_speed_radps').value)
        )
        self.max_linear_speed = max(
            self.default_linear_speed,
            float(self.get_parameter('max_linear_speed_mps').value),
        )
        self.max_lateral_speed = max(
            self.default_lateral_speed,
            float(self.get_parameter('max_lateral_speed_mps').value),
        )
        self.max_angular_speed = max(
            self.default_angular_speed,
            float(self.get_parameter('max_angular_speed_radps').value),
        )
        self.odom_topic = str(self.get_parameter('odom_topic').value)
        self.wheel_odom_topic = str(self.get_parameter('wheel_odom_topic').value)
        self.imu_topic = str(self.get_parameter('imu_topic').value)
        self.diagnostics_topic = str(self.get_parameter('diagnostics_topic').value)
        self.runtime_dir = Path(
            str(self.get_parameter('runtime_dir').value)
        ).expanduser()
        self.activity_limit = max(
            100, int(self.get_parameter('activity_limit').value)
        )
        self.stop_hold_sec = max(
            0.2, float(self.get_parameter('stop_hold_sec').value)
        )

        self.identity = read_yaml(
            self.identity_path,
            {
                'robot_id': 'sverh-rover-0001',
                'hostname': socket.gethostname(),
                'company': 'Сверх',
                'model': 'mecanum-rover-v1',
                'software_version': '0.1.0',
            },
        )
        self.rover_config = read_yaml(self.rover_config_path, {})

        self.started_at = time.time()
        self._lock = threading.RLock()
        self._topic_watches: dict[tuple[str, str], TopicWatch] = {}
        self._image_watches: dict[tuple[str, str], ImageWatch] = {}
        self._publisher_cache: dict[tuple[str, str], PublisherHandle] = {}
        self._service_client_cache: dict[tuple[str, str], ServiceHandle] = {}
        self._latest_drive_command = Twist()
        self._latest_drive_monotonic = 0.0
        self._drive_active = False
        self._stop_until = 0.0

        self._odom: Odometry | None = None
        self._wheel_odom: Odometry | None = None
        self._imu: Imu | None = None
        self._diagnostics: list[dict[str, Any]] = []
        self._topic_state = {
            'odom': TopicSnapshot(),
            'wheel_odometry': TopicSnapshot(),
            'imu': TopicSnapshot(),
            'diagnostics': TopicSnapshot(),
        }
        self._web_clients: dict[str, dict[str, Any]] = {}
        self._activity: deque[dict[str, Any]] = deque(maxlen=self.activity_limit)
        self._motion_process: subprocess.Popen[str] | None = None
        self._motion_started_at: float | None = None
        self._motion_command: list[str] = []
        self._motion_log: deque[str] = deque(maxlen=500)
        self._motion_return_code: int | None = None

        self._cpu_last_total = 0
        self._cpu_last_idle = 0
        self._system_cache_monotonic = 0.0
        self._system_cache: dict[str, Any] = {}
        self._graph_cache_monotonic = 0.0
        self._graph_cache: dict[str, Any] = {}
        self._last_ip_check = 0.0
        self._cached_ip_addresses: list[str] = []

        self.drive_publisher = self.create_publisher(Twist, self.command_topic, 10)
        self.create_subscription(Odometry, self.odom_topic, self._odom_callback, 20)
        self.create_subscription(
            Odometry,
            self.wheel_odom_topic,
            self._wheel_odom_callback,
            20,
        )
        self.create_subscription(
            Imu,
            self.imu_topic,
            self._imu_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            DiagnosticArray,
            self.diagnostics_topic,
            self._diagnostics_callback,
            10,
        )
        self.create_timer(0.05, self._drive_output_timer)
        self.create_timer(1.0, self._maintenance_timer)

        self.plans_directory.mkdir(parents=True, exist_ok=True)
        self._seed_default_plans()
        self.record_activity('system', 'Web gateway started', {'port': self.port})

        handler = self._build_handler()
        self._http_server = ThreadingHTTPServer((self.bind_address, self.port), handler)
        self._http_server.daemon_threads = True
        self._http_server.gateway = self  # type: ignore[attr-defined]
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever,
            name='rover-web-http',
            daemon=True,
        )
        self._http_thread.start()

        addresses = current_ipv4_addresses()
        address_list = ', '.join(addresses) if addresses else 'no IPv4 detected'
        self.get_logger().info(
            f'Rover web listening on http://{self.bind_address}:{self.port} '
            f'(LAN addresses: {address_list})'
        )

    def _touch_snapshot(self, key: str) -> None:
        snapshot = self._topic_state[key]
        snapshot.received_monotonic = time.monotonic()
        snapshot.message_count += 1

    def _odom_callback(self, message: Odometry) -> None:
        with self._lock:
            self._odom = message
            self._touch_snapshot('odom')

    def _wheel_odom_callback(self, message: Odometry) -> None:
        with self._lock:
            self._wheel_odom = message
            self._touch_snapshot('wheel_odometry')

    def _imu_callback(self, message: Imu) -> None:
        with self._lock:
            self._imu = message
            self._touch_snapshot('imu')

    def _diagnostics_callback(self, message: DiagnosticArray) -> None:
        converted: list[dict[str, Any]] = []
        for status in message.status[:100]:
            level = status.level
            if isinstance(level, (bytes, bytearray, memoryview)):
                level_value = int(level[0]) if len(level) > 0 else 0
            else:
                level_value = int(level)
            converted.append({
                'name': status.name,
                'hardware_id': status.hardware_id,
                'level': level_value,
                'message': status.message,
                'values': {
                    item.key: item.value
                    for item in status.values[:40]
                },
            })
        with self._lock:
            self._diagnostics = converted
            self._touch_snapshot('diagnostics')

    def _topic_graph(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        topic_types = {
            name: list(types)
            for name, types in self.get_topic_names_and_types()
        }
        service_types = {
            name: list(types)
            for name, types in self.get_service_names_and_types()
        }
        return topic_types, service_types

    def _resolve_topic_type(
        self,
        topic: str,
        requested_type: str | None = None,
    ) -> tuple[str, list[str]]:
        topic_types, _ = self._topic_graph()
        available_types = topic_types.get(topic, [])
        if requested_type:
            return requested_type, available_types
        if not available_types:
            raise ValueError(f'No ROS type is currently visible for topic {topic}')
        return available_types[0], available_types

    def _resolve_service_type(
        self,
        service: str,
        requested_type: str | None = None,
    ) -> tuple[str, list[str]]:
        _, service_types = self._topic_graph()
        available_types = service_types.get(service, [])
        if requested_type:
            return requested_type, available_types
        if not available_types:
            raise ValueError(f'No ROS type is currently visible for service {service}')
        return available_types[0], available_types

    def _message_summary(self, message: Any) -> Any:
        return sanitize_payload(message_to_ordereddict(message))

    def _ensure_topic_watch(self, topic: str, type_name: str) -> TopicWatch:
        key = (topic, type_name)
        with self._lock:
            existing = self._topic_watches.get(key)
            if existing is not None:
                existing.last_access_monotonic = time.monotonic()
                return existing

            msg_class = get_message(type_name)

            def callback(message: Any) -> None:
                with self._lock:
                    watch = self._topic_watches.get(key)
                    if watch is None:
                        return
                    watch.last_updated_monotonic = time.monotonic()
                    watch.message_count += 1
                    watch.last_error = None
                    try:
                        watch.last_message = self._message_summary(message)
                    except Exception as exc:
                        watch.last_message = {
                            'summary_error': f'{type(exc).__name__}: {exc}'
                        }
                        watch.last_error = str(exc)

            subscription = self.create_subscription(
                msg_class,
                topic,
                callback,
                10,
            )
            watch = TopicWatch(
                topic=topic,
                type_name=type_name,
                msg_class=msg_class,
                subscription=subscription,
                last_access_monotonic=time.monotonic(),
            )
            self._topic_watches[key] = watch
            return watch

    def _reshape_raw_image(
        self,
        message: Image,
        *,
        channels: int,
    ) -> np.ndarray:
        expected_row_size = int(message.width * channels)
        if message.step < expected_row_size:
            raise ValueError('Image step is smaller than expected row size')

        data = np.frombuffer(message.data, dtype=np.uint8)
        expected_bytes = int(message.step * message.height)
        if data.size < expected_bytes:
            raise ValueError('Image payload is shorter than expected')

        rows = data[:expected_bytes].reshape((message.height, message.step))
        cropped = rows[:, :expected_row_size]
        if channels == 1:
            return cropped.reshape((message.height, message.width))
        return cropped.reshape((message.height, message.width, channels))

    def _encode_image_message(self, message: Image) -> tuple[bytes, str, int, int, str]:
        encoding = message.encoding.lower()
        if encoding == 'bgr8':
            frame = self._reshape_raw_image(message, channels=3)
        elif encoding == 'rgb8':
            frame = cv2.cvtColor(
                self._reshape_raw_image(message, channels=3),
                cv2.COLOR_RGB2BGR,
            )
        elif encoding == 'mono8':
            frame = self._reshape_raw_image(message, channels=1)
        elif encoding == 'bgra8':
            frame = cv2.cvtColor(
                self._reshape_raw_image(message, channels=4),
                cv2.COLOR_BGRA2BGR,
            )
        elif encoding == 'rgba8':
            frame = cv2.cvtColor(
                self._reshape_raw_image(message, channels=4),
                cv2.COLOR_RGBA2BGR,
            )
        else:
            raise ValueError(f'Unsupported image encoding: {message.encoding}')

        ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            raise ValueError('OpenCV could not encode frame as JPEG')
        return (
            encoded.tobytes(),
            'image/jpeg',
            int(message.width),
            int(message.height),
            message.encoding,
        )

    def _ensure_image_watch(self, topic: str, type_name: str) -> ImageWatch:
        key = (topic, type_name)
        with self._lock:
            existing = self._image_watches.get(key)
            if existing is not None:
                existing.last_access_monotonic = time.monotonic()
                return existing

            if type_name == 'sensor_msgs/msg/Image':

                def callback(message: Image) -> None:
                    with self._lock:
                        watch = self._image_watches.get(key)
                        if watch is None:
                            return
                        watch.last_access_monotonic = time.monotonic()
                        watch.last_updated_monotonic = time.monotonic()
                        watch.message_count += 1
                        try:
                            (
                                watch.frame_bytes,
                                watch.content_type,
                                watch.width,
                                watch.height,
                                watch.encoding,
                            ) = self._encode_image_message(message)
                            watch.last_error = None
                        except Exception as exc:
                            watch.last_error = f'{type(exc).__name__}: {exc}'

                subscription = self.create_subscription(
                    Image,
                    topic,
                    callback,
                    qos_profile_sensor_data,
                )

            elif type_name == 'sensor_msgs/msg/CompressedImage':

                def callback(message: CompressedImage) -> None:
                    with self._lock:
                        watch = self._image_watches.get(key)
                        if watch is None:
                            return
                        watch.last_access_monotonic = time.monotonic()
                        watch.last_updated_monotonic = time.monotonic()
                        watch.message_count += 1
                        watch.frame_bytes = bytes(message.data)
                        watch.content_type = compressed_content_type(message.format)
                        watch.width = 0
                        watch.height = 0
                        watch.encoding = message.format or 'compressed'
                        watch.last_error = None

                subscription = self.create_subscription(
                    CompressedImage,
                    topic,
                    callback,
                    qos_profile_sensor_data,
                )

            else:
                raise ValueError(f'Unsupported image topic type: {type_name}')

            watch = ImageWatch(
                topic=topic,
                type_name=type_name,
                subscription=subscription,
                last_access_monotonic=time.monotonic(),
            )
            self._image_watches[key] = watch
            return watch

    def _ensure_publisher(self, topic: str, type_name: str) -> PublisherHandle:
        key = (topic, type_name)
        with self._lock:
            existing = self._publisher_cache.get(key)
            if existing is not None:
                return existing
            msg_class = get_message(type_name)
            publisher = self.create_publisher(msg_class, topic, 10)
            handle = PublisherHandle(
                topic=topic,
                type_name=type_name,
                msg_class=msg_class,
                publisher=publisher,
            )
            self._publisher_cache[key] = handle
            return handle

    def _ensure_service_client(self, service: str, type_name: str) -> ServiceHandle:
        key = (service, type_name)
        with self._lock:
            existing = self._service_client_cache.get(key)
            if existing is not None:
                return existing
            srv_class = get_service(type_name)
            client = self.create_client(srv_class, service)
            handle = ServiceHandle(
                service=service,
                type_name=type_name,
                srv_class=srv_class,
                client=client,
            )
            self._service_client_cache[key] = handle
            return handle

    def _maintenance_timer(self) -> None:
        cutoff = time.monotonic() - 10.0
        with self._lock:
            expired = [
                key
                for key, value in self._web_clients.items()
                if value.get('last_seen', 0.0) < cutoff
            ]
            for key in expired:
                del self._web_clients[key]

            process = self._motion_process
            if process is not None:
                return_code = process.poll()
                if return_code is not None:
                    self._motion_return_code = return_code
                    self._motion_process = None
                    self.record_activity(
                        'routes',
                        'Motion process finished',
                        {'return_code': return_code},
                    )

    def record_activity(
        self,
        source: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        item = {
            'timestamp': time.time(),
            'source': source[:64],
            'message': message[:300],
            'details': sanitize_payload(details or {}),
        }
        with self._lock:
            self._activity.append(item)

    def register_heartbeat(self, session_id: str, page: str, client_ip: str) -> None:
        if not session_id or len(session_id) > 128:
            return
        with self._lock:
            self._web_clients[session_id] = {
                'session_id': session_id,
                'page': page[:64],
                'client_ip': client_ip,
                'last_seen': time.monotonic(),
            }

    def request_stop(
        self,
        source: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._stop_until = max(
                self._stop_until,
                time.monotonic() + self.stop_hold_sec,
            )
            self._latest_drive_command = Twist()
            self._latest_drive_monotonic = time.monotonic()
        self.record_activity(source, 'Software STOP requested', details or {})

    def identity_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._last_ip_check > 10.0 or not self._cached_ip_addresses:
                self._cached_ip_addresses = current_ipv4_addresses()
                self._last_ip_check = now
            addresses = list(self._cached_ip_addresses)
        payload = dict(self.identity)
        payload['runtime_hostname'] = socket.gethostname()
        payload['ip_addresses'] = addresses
        return payload

    def _seed_default_plans(self) -> None:
        if any(self.plans_directory.glob('*.yaml')):
            return
        if not self.seed_plans_directory.is_dir():
            return
        for source in sorted(self.seed_plans_directory.glob('*.yaml')):
            target = self.plans_directory / source.name
            if target.exists():
                continue
            try:
                shutil.copy2(source, target)
            except OSError:
                continue

    def _pose_payload(self, message: Odometry | None) -> dict[str, Any] | None:
        if message is None:
            return None
        return {
            'x': float(message.pose.pose.position.x),
            'y': float(message.pose.pose.position.y),
            'yaw': quaternion_yaw(message),
            'vx': float(message.twist.twist.linear.x),
            'vy': float(message.twist.twist.linear.y),
            'wz': float(message.twist.twist.angular.z),
            'frame_id': message.header.frame_id,
            'child_frame_id': message.child_frame_id,
        }

    def _cpu_percent(self) -> float | None:
        try:
            fields = [
                int(value)
                for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:]
            ]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            total = sum(fields)
            if self._cpu_last_total == 0:
                value = None
            else:
                total_delta = total - self._cpu_last_total
                idle_delta = idle - self._cpu_last_idle
                value = (
                    None
                    if total_delta <= 0
                    else 100.0 * (1.0 - idle_delta / total_delta)
                )
            self._cpu_last_total = total
            self._cpu_last_idle = idle
            return value
        except (OSError, ValueError, IndexError):
            return None

    def public_config_payload(self) -> dict[str, Any]:
        geometry = self.rover_config.get('geometry', {})
        encoders = self.rover_config.get('encoders', {})
        base = self.rover_config.get('base_driver', {})
        return {
            'command_topic': self.command_topic,
            'drive_command_timeout_sec': self.drive_command_timeout_sec,
            'drive_defaults': {
                'linear_x': self.default_linear_speed,
                'linear_y': self.default_lateral_speed,
                'angular_z': self.default_angular_speed,
            },
            'drive_limits': {
                'linear_x': self.max_linear_speed,
                'linear_y': self.max_lateral_speed,
                'angular_z': self.max_angular_speed,
            },
            'odom_topic': self.odom_topic,
            'wheel_odom_topic': self.wheel_odom_topic,
            'imu_topic': self.imu_topic,
            'diagnostics_topic': self.diagnostics_topic,
            'plans_directory': str(self.plans_directory),
            'web': {
                'terminal_enabled': self.terminal_enabled,
                'terminal_url': self.terminal_url,
                'terminal_port': self.terminal_port,
                'terminal_path': self.terminal_path,
            },
            'geometry': geometry,
            'encoders': encoders,
            'limits': {
                'max_wheel_speed_mps': base.get('max_wheel_speed_mps', 0.35),
                'command_timeout_sec': base.get('command_timeout_sec', 0.5),
                'feedback_timeout_sec': base.get('feedback_timeout_sec', 0.35),
            },
            'recommended': {
                'manual_linear_speed_mps': min(self.max_linear_speed, 0.18),
                'manual_lateral_speed_mps': min(self.max_lateral_speed, 0.16),
                'manual_angular_speed_radps': min(self.max_angular_speed, 0.70),
            },
        }

    def _system_summary(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._system_cache_monotonic < 0.5 and self._system_cache:
                return dict(self._system_cache)

        temperature_c = None
        try:
            raw = Path('/sys/class/thermal/thermal_zone0/temp').read_text().strip()
            temperature_c = int(raw) / 1000.0
        except (OSError, ValueError):
            pass

        memory_total = None
        memory_available = None
        try:
            values: dict[str, int] = {}
            for line in Path('/proc/meminfo').read_text().splitlines():
                key, value = line.split(':', 1)
                values[key] = int(value.strip().split()[0]) * 1024
            memory_total = values.get('MemTotal')
            memory_available = values.get('MemAvailable')
        except (OSError, ValueError, IndexError):
            pass

        disk_total = disk_free = None
        try:
            usage = shutil.disk_usage('/')
            disk_total = usage.total
            disk_free = usage.free
        except OSError:
            pass

        load_1 = load_5 = load_15 = None
        try:
            load_1, load_5, load_15 = os.getloadavg()
        except OSError:
            pass

        uptime_sec = None
        try:
            uptime_sec = float(Path('/proc/uptime').read_text().split()[0])
        except (OSError, ValueError, IndexError):
            uptime_sec = max(0.0, time.time() - self.started_at)

        throttled = 'unavailable'
        try:
            result = subprocess.run(
                ['vcgencmd', 'get_throttled'],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.4,
            )
            throttled = result.stdout.strip() or 'unavailable'
        except (OSError, subprocess.SubprocessError):
            pass

        payload = {
            'ok': True,
            'hostname': socket.gethostname(),
            'ip_addresses': self.identity_payload().get('ip_addresses', []),
            'bind_address': self.bind_address,
            'port': self.port,
            'started_at': self.started_at,
            'uptime_sec': uptime_sec,
            'cpu_percent': self._cpu_percent(),
            'temperature_c': temperature_c,
            'memory_total_bytes': memory_total,
            'memory_available_bytes': memory_available,
            'disk_total_bytes': disk_total,
            'disk_free_bytes': disk_free,
            'throttled': throttled,
            'load_average': {
                'one_min': load_1,
                'five_min': load_5,
                'fifteen_min': load_15,
            },
            'command_topic': self.command_topic,
            'drive_command_timeout_sec': self.drive_command_timeout_sec,
            'drive_defaults': {
                'linear_x': self.default_linear_speed,
                'linear_y': self.default_lateral_speed,
                'angular_z': self.default_angular_speed,
            },
            'drive_limits': {
                'linear_x': self.max_linear_speed,
                'linear_y': self.max_lateral_speed,
                'angular_z': self.max_angular_speed,
            },
            'devices': self._devices_payload(),
            'ros': self._graph_counts(),
        }
        with self._lock:
            self._system_cache_monotonic = now
            self._system_cache = dict(payload)
        return payload

    def _graph_counts(self) -> dict[str, int]:
        graph = self._graph_payload()
        return {
            'nodes': len(graph['nodes']),
            'topics': len(graph['topics']),
            'services': len(graph['services']),
            'image_topics': len(graph['image_topics']),
        }

    def _devices_payload(self) -> dict[str, Any]:
        path = self.runtime_dir / 'devices.json'
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            return {
                'available': isinstance(value, dict),
                'path': str(path),
                'devices': value if isinstance(value, dict) else {},
            }
        except (OSError, json.JSONDecodeError):
            return {'available': False, 'path': str(path), 'devices': {}}

    def status_payload(self) -> dict[str, Any]:
        with self._lock:
            diagnostics = list(self._diagnostics)
            clients = [dict(value) for value in self._web_clients.values()]
            for client in clients:
                client.pop('last_seen', None)
            topic_state = {
                key: {
                    'age_sec': age_seconds(value.received_monotonic),
                    'message_count': value.message_count,
                }
                for key, value in self._topic_state.items()
            }
            odom = self._pose_payload(self._odom)
            wheel_odom = self._pose_payload(self._wheel_odom)
            imu = None
            if self._imu is not None:
                imu = {
                    'angular_velocity_z': float(self._imu.angular_velocity.z),
                    'linear_acceleration_x': float(self._imu.linear_acceleration.x),
                    'linear_acceleration_y': float(self._imu.linear_acceleration.y),
                    'linear_acceleration_z': float(self._imu.linear_acceleration.z),
                    'frame_id': self._imu.header.frame_id,
                }
            motion = self.motion_status_payload_locked()

        highest_level = max((entry['level'] for entry in diagnostics), default=-1)
        return {
            'ok': True,
            'server_time': time.time(),
            'identity': self.identity_payload(),
            'system': self._system_summary(),
            'topics': topic_state,
            'device_discovery': self._devices_payload(),
            'odom': odom,
            'wheel_odometry': wheel_odom,
            'imu': imu,
            'diagnostics': {
                'highest_level': highest_level,
                'items': diagnostics,
            },
            'clients': clients,
            'connected_clients': len(clients),
            'drive_clients': sum(1 for item in clients if item.get('page') == 'drive'),
            'motion': motion,
        }

    def activity_payload(self, limit: int) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 1000)
        with self._lock:
            return list(self._activity)[-limit:][::-1]

    def list_plans(self) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        for path in sorted(self.plans_directory.glob('*.yaml')):
            try:
                stat = path.stat()
                plan = read_yaml(path, {})
                steps = plan.get('steps', [])
                plans.append({
                    'name': path.name,
                    'size_bytes': stat.st_size,
                    'modified': stat.st_mtime,
                    'steps': len(steps) if isinstance(steps, list) else 0,
                })
            except OSError:
                continue
        return plans

    def _safe_plan_path(self, name: str) -> Path:
        name = unquote(name)
        if not PLAN_NAME_RE.fullmatch(name) or not name.endswith(('.yaml', '.yml')):
            raise ValueError('Invalid plan name')
        path = (self.plans_directory / name).resolve()
        if path.parent != self.plans_directory.resolve():
            raise ValueError('Invalid plan path')
        return path

    def read_plan(self, name: str) -> dict[str, Any]:
        path = self._safe_plan_path(name)
        if not path.exists():
            raise FileNotFoundError(name)
        value = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Plan must contain a YAML object')
        return value

    def save_plan(self, name: str, plan: dict[str, Any]) -> None:
        steps = plan.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('Plan requires a non-empty steps list')
        path = self._safe_plan_path(name)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            encoding='utf-8',
        )
        temporary.replace(path)
        self.record_activity('routes', 'Plan saved', {'name': name, 'steps': len(steps)})

    def _graph_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._graph_cache_monotonic < 0.5 and self._graph_cache:
                return dict(self._graph_cache)

        topic_types, service_types = self._topic_graph()
        nodes = [
            {
                'name': name,
                'namespace': namespace,
                'full_name': f'{namespace.rstrip("/")}/{name}'.replace('//', '/'),
            }
            for name, namespace in sorted(self.get_node_names_and_namespaces())
        ]
        topics = []
        image_topics = []
        for name, types in sorted(topic_types.items()):
            entry = {
                'name': name,
                'types': types,
                'publishers': self.count_publishers(name),
                'subscribers': self.count_subscribers(name),
                'is_image': any(item in IMAGE_TOPIC_TYPES for item in types),
            }
            topics.append(entry)
            if entry['is_image']:
                image_topics.append(entry)

        services = [
            {
                'name': name,
                'types': types,
            }
            for name, types in sorted(service_types.items())
        ]

        payload = {
            'ok': True,
            'nodes': nodes,
            'topics': topics,
            'services': services,
            'image_topics': image_topics,
        }
        with self._lock:
            self._graph_cache_monotonic = now
            self._graph_cache = dict(payload)
        return payload

    def inspect_topic(self, topic_name: str, type_name: str | None = None) -> dict[str, Any]:
        topic = normalize_topic_name(topic_name)
        resolved_type, available_types = self._resolve_topic_type(topic, type_name)
        if resolved_type in IMAGE_TOPIC_TYPES:
            watch = self._ensure_image_watch(topic, resolved_type)
            return {
                'ok': True,
                'kind': 'image',
                'topic': topic,
                'type': resolved_type,
                'available_types': available_types,
                'publishers': self.count_publishers(topic),
                'subscribers': self.count_subscribers(topic),
                'message_count': watch.message_count,
                'age_sec': age_seconds(watch.last_updated_monotonic),
                'frame_url': (
                    f'/api/camera/frame?topic={topic}&type={resolved_type}'
                ),
                'width': watch.width,
                'height': watch.height,
                'encoding': watch.encoding,
                'last_error': watch.last_error,
            }

        watch = self._ensure_topic_watch(topic, resolved_type)
        return {
            'ok': True,
            'kind': 'message',
            'topic': topic,
            'type': resolved_type,
            'available_types': available_types,
            'publishers': self.count_publishers(topic),
            'subscribers': self.count_subscribers(topic),
            'message_count': watch.message_count,
            'age_sec': age_seconds(watch.last_updated_monotonic),
            'last_error': watch.last_error,
            'template': make_message_template(watch.msg_class),
            'latest_message': watch.last_message,
        }

    def publish_topic(
        self,
        topic_name: str,
        payload: dict[str, Any],
        type_name: str | None = None,
    ) -> dict[str, Any]:
        topic = normalize_topic_name(topic_name)
        resolved_type, _ = self._resolve_topic_type(topic, type_name)
        if resolved_type in IMAGE_TOPIC_TYPES:
            raise ValueError('Publishing image topics from the web UI is not supported yet')

        handle = self._ensure_publisher(topic, resolved_type)
        message = handle.msg_class()
        if not isinstance(payload, dict):
            raise ValueError('Topic payload must be a JSON object')
        set_message_fields(message, payload)
        handle.publisher.publish(message)
        self.record_activity(
            'ros',
            'Topic published',
            {'topic': topic, 'type': resolved_type},
        )
        return {
            'ok': True,
            'topic': topic,
            'type': resolved_type,
        }

    def inspect_service(
        self,
        service_name: str,
        type_name: str | None = None,
    ) -> dict[str, Any]:
        service = normalize_service_name(service_name)
        resolved_type, available_types = self._resolve_service_type(service, type_name)
        handle = self._ensure_service_client(service, resolved_type)
        return {
            'ok': True,
            'service': service,
            'type': resolved_type,
            'available_types': available_types,
            'ready': bool(handle.client.service_is_ready()),
            'request_template': make_message_template(handle.srv_class.Request),
        }

    def call_service(
        self,
        service_name: str,
        request_payload: dict[str, Any],
        type_name: str | None = None,
    ) -> dict[str, Any]:
        service = normalize_service_name(service_name)
        resolved_type, _ = self._resolve_service_type(service, type_name)
        handle = self._ensure_service_client(service, resolved_type)

        if not isinstance(request_payload, dict):
            raise ValueError('Service request must be a JSON object')

        if not handle.client.wait_for_service(timeout_sec=1.5):
            raise RuntimeError(f'Service {service} is not available')

        request = handle.srv_class.Request()
        set_message_fields(request, request_payload)

        started = time.monotonic()
        future = handle.client.call_async(request)
        deadline = started + 3.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done():
            raise RuntimeError(f'Service call timed out for {service}')

        response = future.result()
        if response is None:
            raise RuntimeError(f'Service {service} returned no response')

        duration = time.monotonic() - started
        self.record_activity(
            'ros',
            'Service called',
            {
                'service': service,
                'type': resolved_type,
                'duration_sec': duration,
            },
        )
        return {
            'ok': True,
            'service': service,
            'type': resolved_type,
            'duration_sec': duration,
            'response': sanitize_payload(message_to_ordereddict(response)),
        }

    def camera_topics(self) -> dict[str, Any]:
        graph = self._graph_payload()
        return {'ok': True, 'topics': graph['image_topics']}

    def camera_status(
        self,
        topic_name: str,
        type_name: str | None = None,
    ) -> dict[str, Any]:
        topic = normalize_topic_name(topic_name)
        resolved_type, available_types = self._resolve_topic_type(topic, type_name)
        if resolved_type not in IMAGE_TOPIC_TYPES:
            raise ValueError(f'Topic {topic} is not an image topic')
        watch = self._ensure_image_watch(topic, resolved_type)
        return {
            'ok': True,
            'topic': topic,
            'type': resolved_type,
            'available_types': available_types,
            'width': watch.width,
            'height': watch.height,
            'encoding': watch.encoding,
            'message_count': watch.message_count,
            'age_sec': age_seconds(watch.last_updated_monotonic),
            'frame_ready': watch.frame_bytes is not None,
            'last_error': watch.last_error,
            'frame_url': f'/api/camera/frame?topic={topic}&type={resolved_type}',
        }

    def camera_frame(
        self,
        topic_name: str,
        type_name: str | None = None,
    ) -> tuple[bytes, str]:
        topic = normalize_topic_name(topic_name)
        resolved_type, _ = self._resolve_topic_type(topic, type_name)
        watch = self._ensure_image_watch(topic, resolved_type)
        if watch.frame_bytes is None:
            raise RuntimeError(f'No frame received yet from {topic}')
        return watch.frame_bytes, watch.content_type

    def drive_payload(self) -> dict[str, Any]:
        with self._lock:
            latest = self._latest_drive_command
            active = self._drive_active
            timestamp = self._latest_drive_monotonic
        return {
            'ok': True,
            'command_topic': self.command_topic,
            'timeout_sec': self.drive_command_timeout_sec,
            'defaults': {
                'linear_x': self.default_linear_speed,
                'linear_y': self.default_lateral_speed,
                'angular_z': self.default_angular_speed,
            },
            'limits': {
                'linear_x': self.max_linear_speed,
                'linear_y': self.max_lateral_speed,
                'angular_z': self.max_angular_speed,
            },
            'active': active,
            'age_sec': age_seconds(timestamp),
            'last_command': {
                'linear_x': float(latest.linear.x),
                'linear_y': float(latest.linear.y),
                'angular_z': float(latest.angular.z),
            },
        }

    def set_drive_command(self, linear_x: float, linear_y: float, angular_z: float) -> dict[str, Any]:
        command = Twist()
        command.linear.x = clamp(float(linear_x), self.max_linear_speed)
        command.linear.y = clamp(float(linear_y), self.max_lateral_speed)
        command.angular.z = clamp(float(angular_z), self.max_angular_speed)
        with self._lock:
            self._latest_drive_command = command
            self._latest_drive_monotonic = time.monotonic()
        return {
            'ok': True,
            'command': {
                'linear_x': command.linear.x,
                'linear_y': command.linear.y,
                'angular_z': command.angular.z,
            },
        }

    def stop_drive(self) -> dict[str, Any]:
        return self.set_drive_command(0.0, 0.0, 0.0)

    def _drive_output_timer(self) -> None:
        now = time.monotonic()
        with self._lock:
            fresh = now - self._latest_drive_monotonic <= self.drive_command_timeout_sec
            command = self._latest_drive_command
            was_active = self._drive_active
            stop_active = now < self._stop_until
            self._drive_active = fresh and not stop_active

        if stop_active:
            self.drive_publisher.publish(Twist())
        elif fresh:
            self.drive_publisher.publish(command)
        elif was_active:
            self.drive_publisher.publish(Twist())

    def start_motion(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._motion_process is not None and self._motion_process.poll() is None:
                raise RuntimeError('A motion command is already running')

        if not self.executor_path.exists():
            raise FileNotFoundError(f'Motion executor not found: {self.executor_path}')

        kind = str(request.get('kind', '')).strip()
        command = [
            sys.executable,
            str(self.executor_path),
            '--odom-topic',
            self.odom_topic,
            '--cmd-vel-topic',
            self.command_topic,
        ]
        summary: dict[str, Any] = {'kind': kind}

        if kind == 'plan':
            name = str(request.get('name', ''))
            path = self._safe_plan_path(name)
            if not path.exists():
                raise FileNotFoundError(name)
            command += ['run', str(path)]
            summary['name'] = name
        elif kind == 'move':
            forward = float(request.get('forward', 0.0))
            left = float(request.get('left', 0.0))
            speed = float(request.get('speed', 0.15))
            if abs(forward) > 5.0 or abs(left) > 5.0:
                raise ValueError('Move distance is limited to 5 m per command')
            if not 0.10 <= speed <= 0.35:
                raise ValueError('Move speed must be between 0.10 and 0.35 m/s')
            command += [
                'move',
                '--forward',
                str(forward),
                '--left',
                str(left),
                '--speed',
                str(speed),
            ]
            summary.update({'forward': forward, 'left': left, 'speed': speed})
        elif kind == 'turn':
            degrees = float(request.get('degrees', 0.0))
            speed = float(request.get('speed', 0.25))
            tolerance = float(request.get('tolerance_deg', 3.0))
            if abs(degrees) > 720.0:
                raise ValueError('Turn is limited to 720 degrees per command')
            if not 0.10 <= speed <= 1.0:
                raise ValueError('Angular speed must be between 0.10 and 1.0 rad/s')
            if not 1.0 <= tolerance <= 15.0:
                raise ValueError('Tolerance must be between 1 and 15 degrees')
            command += [
                'turn',
                str(degrees),
                '--speed',
                str(speed),
                '--tolerance-deg',
                str(tolerance),
            ]
            summary.update({
                'degrees': degrees,
                'speed': speed,
                'tolerance_deg': tolerance,
            })
        else:
            raise ValueError('Unknown motion kind')

        environment = os.environ.copy()
        environment.setdefault('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
        process = subprocess.Popen(
            command,
            cwd=str(self.executor_path.parent.parent),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        with self._lock:
            self._motion_process = process
            self._motion_started_at = time.time()
            self._motion_command = command
            self._motion_log.clear()
            self._motion_return_code = None

        threading.Thread(
            target=self._read_motion_output,
            args=(process,),
            name='rover-motion-output',
            daemon=True,
        ).start()
        self.record_activity('routes', 'Motion process started', summary)
        return self.motion_status_payload()

    def _read_motion_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            cleaned = line.rstrip('\r\n')
            with self._lock:
                self._motion_log.append(cleaned)

    def stop_motion(self, *, request_stop: bool = True) -> dict[str, Any]:
        with self._lock:
            process = self._motion_process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            threading.Thread(
                target=self._ensure_motion_stopped,
                args=(process,),
                name='rover-motion-stop',
                daemon=True,
            ).start()
        if request_stop:
            self.request_stop('routes', {'reason': 'motion stop endpoint'})
        return self.motion_status_payload()

    def _ensure_motion_stopped(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def motion_status_payload_locked(self) -> dict[str, Any]:
        process = self._motion_process
        running = process is not None and process.poll() is None
        return {
            'running': running,
            'pid': process.pid if running and process is not None else None,
            'started_at': self._motion_started_at,
            'return_code': self._motion_return_code,
            'command': list(self._motion_command),
            'log': list(self._motion_log)[-120:],
        }

    def motion_status_payload(self) -> dict[str, Any]:
        with self._lock:
            return self.motion_status_payload_locked()

    def _serve_static_file(self, request_path: str) -> tuple[bytes, str]:
        relative_path = 'index.html' if request_path in ('', '/') else request_path.lstrip('/')
        candidate = os.path.normpath(os.path.join(str(self.web_root), relative_path))
        if os.path.commonpath([str(self.web_root), candidate]) != str(self.web_root):
            raise PermissionError('Forbidden')
        path = Path(candidate)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f'{request_path} not found')
        content_type, _ = mimetypes.guess_type(str(path))
        return path.read_bytes(), content_type or 'application/octet-stream'

    def _build_handler(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'RoverWeb/0.2'

            def do_GET(self) -> None:  # noqa: N802
                try:
                    parsed = urlparse(self.path)
                    path = parsed.path
                    query = parse_qs(parsed.query)

                    if path == '/api/health':
                        self._send_json(
                            {'ok': True, 'service': 'rover_web'},
                            HTTPStatus.OK,
                        )
                        return
                    if path == '/api/identity':
                        self._send_json(gateway.identity_payload(), HTTPStatus.OK)
                        return
                    if path == '/api/config':
                        self._send_json(gateway.public_config_payload(), HTTPStatus.OK)
                        return
                    if path == '/api/status':
                        self._send_json(gateway.status_payload(), HTTPStatus.OK)
                        return
                    if path == '/api/activity':
                        limit_text = self._optional_query(query, 'limit') or '100'
                        self._send_json(
                            {'items': gateway.activity_payload(int(limit_text))},
                            HTTPStatus.OK,
                        )
                        return
                    if path == '/api/system':
                        self._send_json(gateway._system_summary(), HTTPStatus.OK)
                        return
                    if path == '/api/plans':
                        self._send_json(
                            {'plans': gateway.list_plans()},
                            HTTPStatus.OK,
                        )
                        return
                    if path.startswith('/api/plans/'):
                        name = path.removeprefix('/api/plans/')
                        self._send_json(
                            {'name': name, 'plan': gateway.read_plan(name)},
                            HTTPStatus.OK,
                        )
                        return
                    if path == '/api/motion/status':
                        self._send_json(gateway.motion_status_payload(), HTTPStatus.OK)
                        return
                    if path == '/api/ros/graph':
                        self._send_json(gateway._graph_payload(), HTTPStatus.OK)
                        return
                    if path == '/api/ros/topic':
                        topic = self._required_query(query, 'name')
                        type_name = self._optional_query(query, 'type')
                        self._send_json(
                            gateway.inspect_topic(topic, type_name),
                            HTTPStatus.OK,
                        )
                        return
                    if path == '/api/ros/service':
                        service = self._required_query(query, 'name')
                        type_name = self._optional_query(query, 'type')
                        self._send_json(
                            gateway.inspect_service(service, type_name),
                            HTTPStatus.OK,
                        )
                        return
                    if path == '/api/camera/topics':
                        self._send_json(gateway.camera_topics(), HTTPStatus.OK)
                        return
                    if path == '/api/camera/status':
                        topic = self._required_query(query, 'topic')
                        type_name = self._optional_query(query, 'type')
                        self._send_json(
                            gateway.camera_status(topic, type_name),
                            HTTPStatus.OK,
                        )
                        return
                    if path == '/api/camera/frame':
                        topic = self._required_query(query, 'topic')
                        type_name = self._optional_query(query, 'type')
                        frame_bytes, content_type = gateway.camera_frame(topic, type_name)
                        self._send_bytes(frame_bytes, content_type, HTTPStatus.OK)
                        return
                    if path == '/api/drive':
                        self._send_json(gateway.drive_payload(), HTTPStatus.OK)
                        return

                    body, content_type = gateway._serve_static_file(path)
                    self._send_bytes(body, content_type, HTTPStatus.OK, cache=False)
                except FileNotFoundError:
                    self._send_error(HTTPStatus.NOT_FOUND, 'Not found')
                except PermissionError:
                    self._send_error(HTTPStatus.FORBIDDEN, 'Forbidden')
                except ValueError as exc:
                    self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                except RuntimeError as exc:
                    self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
                except Exception as exc:
                    gateway.get_logger().error(f'GET {self.path} failed: {exc}')
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

            def do_POST(self) -> None:  # noqa: N802
                try:
                    parsed = urlparse(self.path)
                    payload = self._read_json_body()
                    if parsed.path == '/api/heartbeat':
                        gateway.register_heartbeat(
                            str(payload.get('session_id', '')),
                            str(payload.get('page', '')),
                            self._client_ip(),
                        )
                        self._send_json({'ok': True}, HTTPStatus.OK)
                        return
                    if parsed.path == '/api/activity':
                        gateway.record_activity(
                            str(payload.get('source', 'web')),
                            str(payload.get('message', 'Activity')),
                            payload.get('details', {})
                            if isinstance(payload.get('details', {}), dict)
                            else {},
                        )
                        self._send_json({'ok': True}, HTTPStatus.OK)
                        return
                    if parsed.path == '/api/stop':
                        details = (
                            payload.get('details', {})
                            if isinstance(payload.get('details', {}), dict)
                            else {}
                        )
                        gateway.request_stop(
                            str(payload.get('source', 'web')),
                            {'client_ip': self._client_ip(), **details},
                        )
                        self._send_json(
                            {
                                'ok': True,
                                'motion': gateway.stop_motion(request_stop=False),
                            },
                            HTTPStatus.OK,
                        )
                        return
                    if parsed.path == '/api/ros/topic/publish':
                        topic = payload.get('topic') or ''
                        type_name = payload.get('type')
                        message = payload.get('message', {})
                        self._send_json(
                            gateway.publish_topic(str(topic), message, type_name),
                            HTTPStatus.OK,
                        )
                        return
                    if parsed.path == '/api/ros/service/call':
                        service = payload.get('service') or ''
                        type_name = payload.get('type')
                        request_payload = payload.get('request', {})
                        self._send_json(
                            gateway.call_service(str(service), request_payload, type_name),
                            HTTPStatus.OK,
                        )
                        return
                    if parsed.path == '/api/drive/command':
                        self._send_json(
                            gateway.set_drive_command(
                                float(payload.get('linear_x', 0.0)),
                                float(payload.get('linear_y', 0.0)),
                                float(payload.get('angular_z', 0.0)),
                            ),
                            HTTPStatus.OK,
                        )
                        return
                    if parsed.path == '/api/drive/stop':
                        self._send_json(gateway.stop_drive(), HTTPStatus.OK)
                        return
                    if parsed.path == '/api/motion/start':
                        self._send_json(
                            {'ok': True, 'motion': gateway.start_motion(payload)},
                            HTTPStatus.OK,
                        )
                        return
                    if parsed.path == '/api/motion/stop':
                        self._send_json(
                            {'ok': True, 'motion': gateway.stop_motion()},
                            HTTPStatus.OK,
                        )
                        return
                    if parsed.path == '/api/plans/save':
                        name = str(payload.get('name', ''))
                        plan = payload.get('plan')
                        if not isinstance(plan, dict):
                            raise ValueError('plan must be an object')
                        gateway.save_plan(name, plan)
                        self._send_json({'ok': True}, HTTPStatus.OK)
                        return
                    self._send_error(HTTPStatus.NOT_FOUND, 'Not found')
                except json.JSONDecodeError:
                    self._send_error(HTTPStatus.BAD_REQUEST, 'Invalid JSON')
                except ValueError as exc:
                    self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                except RuntimeError as exc:
                    self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
                except Exception as exc:
                    gateway.get_logger().error(f'POST {self.path} failed: {exc}')
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

            def _optional_query(
                self,
                query: dict[str, list[str]],
                key: str,
            ) -> str | None:
                values = query.get(key)
                if not values:
                    return None
                text = values[0].strip()
                return text or None

            def _required_query(self, query: dict[str, list[str]], key: str) -> str:
                value = self._optional_query(query, key)
                if value is None:
                    raise ValueError(f'Missing query parameter: {key}')
                return value

            def _client_ip(self) -> str:
                forwarded = self.headers.get('X-Forwarded-For', '').split(',')[0].strip()
                return forwarded or self.client_address[0]

            def _read_json_body(self) -> dict[str, Any]:
                content_length = int(self.headers.get('Content-Length', '0'))
                if content_length > MAX_REQUEST_BYTES:
                    raise ValueError('Request body is too large')
                raw = self.rfile.read(content_length) if content_length > 0 else b'{}'
                decoded = json.loads(raw.decode('utf-8'))
                if not isinstance(decoded, dict):
                    raise ValueError('JSON body must be an object')
                return decoded

            def _send_json(self, payload: dict[str, Any], status: HTTPStatus) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            def _send_bytes(
                self,
                payload: bytes,
                content_type: str,
                status: HTTPStatus,
                *,
                cache: bool = False,
            ) -> None:
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header(
                    'Cache-Control',
                    'public, max-age=3600' if cache else 'no-store',
                )
                self.end_headers()
                self.wfile.write(payload)

            def _send_error(self, status: HTTPStatus, message: str) -> None:
                payload = {'ok': False, 'error': message}
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

        return Handler

    def destroy_node(self) -> bool:
        self.request_stop('system', {'reason': 'gateway shutdown'})
        try:
            self.stop_motion()
        except Exception:
            pass
        try:
            self.drive_publisher.publish(Twist())
        except Exception:
            pass
        try:
            self._http_server.shutdown()
            self._http_server.server_close()
        except Exception:
            pass
        self._http_thread.join(timeout=1.0)
        return super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = RoverWebGateway()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
