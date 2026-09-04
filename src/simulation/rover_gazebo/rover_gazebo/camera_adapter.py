from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image

from rover_interfaces.srv import GetFrame


class CameraAdapter(Node):
    def __init__(self) -> None:
        super().__init__('sim_camera_adapter')
        self.declare_parameter('image_topic', '/image_raw')
        self.declare_parameter('compressed_topic', '/image_raw/compressed')
        self.declare_parameter('get_frame_service', '/get_frame')
        self.declare_parameter('jpeg_quality', 85)
        self.latest: Optional[CompressedImage] = None
        self.latest_width = 0
        self.latest_height = 0
        self.publisher = self.create_publisher(
            CompressedImage,
            str(self.get_parameter('compressed_topic').value),
            qos_profile_sensor_data,
        )
        self.subscription = self.create_subscription(
            Image,
            str(self.get_parameter('image_topic').value),
            self._on_image,
            qos_profile_sensor_data,
        )
        self.service = self.create_service(
            GetFrame,
            str(self.get_parameter('get_frame_service').value),
            self._get_frame,
        )

    @staticmethod
    def _to_bgr(message: Image) -> np.ndarray:
        encoding = message.encoding.lower()
        channels = {
            'mono8': 1,
            'rgb8': 3,
            'bgr8': 3,
            'rgba8': 4,
            'bgra8': 4,
        }.get(encoding)
        if channels is None:
            raise ValueError(f'Unsupported simulated camera encoding: {message.encoding}')
        row_bytes = int(message.step) or int(message.width) * channels
        data = np.frombuffer(bytes(message.data), dtype=np.uint8)
        rows = data[: int(message.height) * row_bytes].reshape(
            int(message.height), row_bytes
        )
        image = rows[:, : int(message.width) * channels].reshape(
            int(message.height), int(message.width), channels
        )
        if encoding == 'rgb8':
            return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if encoding == 'rgba8':
            return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        if encoding == 'bgra8':
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        if encoding == 'mono8':
            return image[:, :, 0]
        return image

    def _on_image(self, message: Image) -> None:
        try:
            quality = max(1, min(100, int(self.get_parameter('jpeg_quality').value)))
            ok, encoded = cv2.imencode(
                '.jpg', self._to_bgr(message), [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if not ok:
                raise ValueError('OpenCV failed to encode simulated camera frame')
            output = CompressedImage()
            output.header = message.header
            output.format = 'jpeg'
            output.data = encoded.tobytes()
            self.latest = output
            self.latest_width = int(message.width)
            self.latest_height = int(message.height)
            self.publisher.publish(output)
        except Exception as exc:
            self.get_logger().error(str(exc), throttle_duration_sec=5.0)

    def _get_frame(
        self,
        _request: GetFrame.Request,
        response: GetFrame.Response,
    ) -> GetFrame.Response:
        if self.latest is None:
            response.success = False
            response.message = 'No simulated camera frame has been received yet'
            return response
        response.success = True
        response.message = 'Latest simulated camera frame'
        response.frame = self.latest
        response.width = self.latest_width
        response.height = self.latest_height
        stamp = rclpy.time.Time.from_msg(self.latest.header.stamp)
        response.age_sec = float((self.get_clock().now() - stamp).nanoseconds / 1e9)
        return response


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node = CameraAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
