from __future__ import annotations

import math
import time
from typing import Optional

import cv2
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


def as_capture_source(device: str) -> str | int:
    text = device.strip()
    if text.isdigit():
        return int(text)
    return text


class UsbCameraNode(Node):
    def __init__(self) -> None:
        super().__init__('usb_camera_node')

        self.declare_parameter('device', '/dev/video0')
        self.declare_parameter('image_topic', '/camera/image_raw')
        self.declare_parameter('frame_id', 'camera_optical_frame')
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 30.0)
        self.declare_parameter('use_mjpeg', True)
        self.declare_parameter('reconnect_interval_sec', 2.0)

        self.device = str(self.get_parameter('device').value)
        self.frame_id = str(self.get_parameter('frame_id').value)
        self.width = int(self.get_parameter('width').value)
        self.height = int(self.get_parameter('height').value)
        self.fps = float(self.get_parameter('fps').value)
        self.use_mjpeg = bool(self.get_parameter('use_mjpeg').value)
        self.reconnect_interval = float(
            self.get_parameter('reconnect_interval_sec').value
        )

        if self.width <= 0 or self.height <= 0:
            raise ValueError('width and height must be positive')
        if not math.isfinite(self.fps) or self.fps <= 0.0:
            raise ValueError('fps must be finite and positive')
        if (
            not math.isfinite(self.reconnect_interval)
            or self.reconnect_interval <= 0.0
        ):
            raise ValueError('reconnect_interval_sec must be finite and positive')

        self.publisher = self.create_publisher(
            Image,
            str(self.get_parameter('image_topic').value),
            qos_profile_sensor_data,
        )

        self.capture: Optional[cv2.VideoCapture] = None
        self.last_open_attempt = 0.0
        self.last_warn_time = 0.0

        self._open_camera(force=True)
        self.create_timer(1.0 / self.fps, self._publish_frame)

    def _open_camera(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self.last_open_attempt < self.reconnect_interval:
            return False

        self.last_open_attempt = now
        self._release_camera()

        source = as_capture_source(self.device)
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
        for backend in backends:
            capture = cv2.VideoCapture(source, backend)
            if capture.isOpened():
                self.capture = capture
                break
            capture.release()
        else:
            self.capture = None

        if self.capture is None or not self.capture.isOpened():
            self._warn_throttled(
                f'Cannot open USB camera {self.device}; retrying automatically'
            )
            self._release_camera()
            return False

        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        self.capture.set(cv2.CAP_PROP_FPS, float(self.fps))
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
        if self.use_mjpeg:
            self.capture.set(
                cv2.CAP_PROP_FOURCC,
                float(cv2.VideoWriter_fourcc(*'MJPG')),
            )

        actual_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        self.get_logger().info(
            f'USB camera connected: {self.device} -> '
            f'{actual_width}x{actual_height} @ {actual_fps:.1f} fps'
        )
        return True

    def _warn_throttled(self, text: str) -> None:
        now = time.monotonic()
        if now - self.last_warn_time >= 2.0:
            self.get_logger().warning(text)
            self.last_warn_time = now

    def _release_camera(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _publish_frame(self) -> None:
        if self.capture is None or not self.capture.isOpened():
            self._open_camera()
            return

        ok, frame = self.capture.read()
        if not ok or frame is None:
            self._warn_throttled(
                f'Failed to read frame from {self.device}; reconnecting'
            )
            self._release_camera()
            return

        if len(frame.shape) != 3 or frame.shape[2] != 3:
            self._warn_throttled(
                'Camera returned a non-BGR frame; skipping this image'
            )
            return

        message = Image()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = self.frame_id
        message.height = int(frame.shape[0])
        message.width = int(frame.shape[1])
        message.encoding = 'bgr8'
        message.is_bigendian = False
        message.step = int(frame.shape[1] * frame.shape[2])
        message.data = frame.tobytes()
        self.publisher.publish(message)

    def close(self) -> None:
        self._release_camera()


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node: Optional[UsbCameraNode] = None
    try:
        node = UsbCameraNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
