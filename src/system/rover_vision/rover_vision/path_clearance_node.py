from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import time
import struct
from urllib.request import urlopen

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from rover_vision.path_clearance import RoadAppearanceModel, TemporalDecision


DEFAULT_ROI = [0.44, 0.52, 0.56, 0.52, 0.64, 0.90, 0.36, 0.90]


def image_message_to_bgr(message: Image) -> np.ndarray:
    if str(message.encoding).lower() != 'bgr8':
        raise ValueError(f'Expected bgr8 input, got {message.encoding}')
    height = int(message.height)
    width = int(message.width)
    row_bytes = width * 3
    step = int(message.step) if int(message.step) > 0 else row_bytes
    if step < row_bytes:
        raise ValueError(f'Image step {step} is smaller than a BGR row {row_bytes}')
    expected = height * step
    data = np.frombuffer(message.data, dtype=np.uint8)
    if data.size != expected:
        raise ValueError(f'Expected {expected} image bytes, got {data.size}')
    rows = data.reshape((height, step))[:, :row_bytes]
    return rows.reshape((height, width, 3)).copy()


class PathClearanceNode(Node):
    def __init__(self) -> None:
        super().__init__('path_clearance_node')
        self.declare_parameter('camera_media_url', 'http://127.0.0.1:8091')
        self.declare_parameter('result_topic', '/path_clearance')
        self.declare_parameter('debug_topic', '/path_clearance/debug/compressed')
        self.declare_parameter(
            'model_path',
            '~/.config/sverk-rover/path_clearance_model.npz',
        )
        self.declare_parameter('roi_points', DEFAULT_ROI)
        self.declare_parameter('calibration_frames', 20)
        self.declare_parameter('force_recalibration', False)
        self.declare_parameter('max_processing_fps', 5.0)
        self.declare_parameter('publish_debug_image', False)
        self.declare_parameter('blocked_fraction_threshold', 0.10)
        self.declare_parameter('component_fraction_threshold', 0.025)
        self.declare_parameter('width_fraction_threshold', 0.55)

        self.camera_media_url = str(self.get_parameter('camera_media_url').value).rstrip('/')
        self._last_camera_sequence = None
        self.model_path = Path(
            str(self.get_parameter('model_path').value)
        ).expanduser()
        self.calibration_frames = max(
            5, int(self.get_parameter('calibration_frames').value)
        )
        self.max_processing_fps = max(
            0.1, float(self.get_parameter('max_processing_fps').value)
        )
        self.publish_debug_image = bool(
            self.get_parameter('publish_debug_image').value
        )
        self._minimum_period = 1.0 / self.max_processing_fps
        self._last_processed_at = 0.0
        self._calibration: deque[np.ndarray] = deque(maxlen=self.calibration_frames)
        self._decision = TemporalDecision()
        self._processed_frames = 0
        self._processing_time_total = 0.0

        force_recalibration = bool(
            self.get_parameter('force_recalibration').value
        )
        if self.model_path.exists() and not force_recalibration:
            self._model = RoadAppearanceModel.load(self.model_path)
            self.get_logger().info(f'Loaded road model from {self.model_path}')
        else:
            self._model = RoadAppearanceModel(
                self.get_parameter('roi_points').value,
                blocked_fraction_threshold=float(
                    self.get_parameter('blocked_fraction_threshold').value
                ),
                component_fraction_threshold=float(
                    self.get_parameter('component_fraction_threshold').value
                ),
                width_fraction_threshold=float(
                    self.get_parameter('width_fraction_threshold').value
                ),
            )
            self.get_logger().warning(
                'Road model is not calibrated. Keep the corridor empty for '
                f'{self.calibration_frames} frames.'
            )

        self._result_publisher = self.create_publisher(
            String,
            str(self.get_parameter('result_topic').value),
            10,
        )
        self._debug_publisher = self.create_publisher(
            CompressedImage,
            str(self.get_parameter('debug_topic').value),
            2,
        ) if self.publish_debug_image else None
        self._camera_timer = self.create_timer(self._minimum_period, self._read_camera)

    def _read_camera(self):
        try:
            with urlopen(self.camera_media_url + '/packet?mode=live', timeout=1.0) as response:
                packet = response.read(16 * 1024 * 1024 + 1)
            if len(packet) < 4 or len(packet) > 16 * 1024 * 1024:
                raise ValueError('Invalid camera packet size')
            size = struct.unpack('!I', packet[:4])[0]
            if size > len(packet) - 4:
                raise ValueError('Truncated camera packet')
            metadata = json.loads(packet[4:4 + size])
            identity = (metadata['stamp']['sec'], metadata['stamp']['nanosec'], metadata['sequence'])
            if identity == self._last_camera_sequence:
                return
            frame = cv2.imdecode(np.frombuffer(packet[4 + size:], np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError('Invalid camera JPEG')
            self._last_camera_sequence = identity
            self._process_frame(frame)
        except Exception as error:
            self._publish_result({'state': 'unavailable', 'error': str(error),
                                  'observation_only': True})

    def _publish_result(self, result: dict) -> None:
        message = String()
        message.data = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        self._result_publisher.publish(message)

    def _publish_debug(
        self,
        frame: np.ndarray,
        state: str,
        warped: np.ndarray | None = None,
        mask: np.ndarray | None = None,
    ) -> None:
        if not self.publish_debug_image:
            return
        annotated = frame.copy()
        points = self._model.source_points(frame.shape).round().astype(np.int32)
        color = (0, 220, 0) if state == 'clear' else (
            (0, 0, 230) if state == 'blocked' else (0, 190, 255)
        )
        cv2.polylines(annotated, [points], True, color, 4)
        cv2.putText(
            annotated,
            f'path: {state}',
            (25, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            color,
            3,
            cv2.LINE_AA,
        )
        annotated = cv2.resize(annotated, (640, 512))
        if warped is not None and mask is not None:
            preview = cv2.resize(warped, (240, 360))
            mask_color = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            mask_color[:, :, 0] = 0
            mask_color[:, :, 1] = 0
            side = np.vstack([preview, mask_color])
            side = cv2.resize(side, (171, 512))
            annotated = np.hstack([annotated, side])
        ok, encoded = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return
        message = CompressedImage()
        message.header.stamp = self.get_clock().now().to_msg()
        message.format = 'jpeg'
        message.data = encoded.tobytes()
        self._debug_publisher.publish(message)

    def _on_image(self, message: Image) -> None:
        self._process_frame(image_message_to_bgr(message))

    def _process_frame(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        if now - self._last_processed_at < self._minimum_period:
            return
        self._last_processed_at = now
        started = time.perf_counter()
        try:
            if not self._model.calibrated:
                self._calibration.append(frame)
                count = len(self._calibration)
                result = {
                    'state': 'calibrating',
                    'calibration_frames': count,
                    'calibration_target': self.calibration_frames,
                }
                self._publish_result(result)
                self._publish_debug(frame, 'calibrating')
                if count >= self.calibration_frames:
                    self._model.fit(self._calibration)
                    self._model.save(self.model_path)
                    self._calibration.clear()
                    self.get_logger().info(
                        f'Calibration complete and saved to {self.model_path}'
                    )
                return

            metrics, warped, mask = self._model.analyze(frame)
            state = self._decision.update(metrics.blocked)
            processing_ms = (time.perf_counter() - started) * 1000.0
            self._processed_frames += 1
            self._processing_time_total += processing_ms
            result = {
                'state': state,
                'instantaneous_blocked': metrics.blocked,
                'anomaly_fraction': round(metrics.anomaly_fraction, 5),
                'largest_component_fraction': round(
                    metrics.largest_component_fraction, 5
                ),
                'max_width_fraction': round(metrics.max_width_fraction, 5),
                'processing_ms': round(processing_ms, 2),
                'mean_processing_ms': round(
                    self._processing_time_total / self._processed_frames,
                    2,
                ),
                'observation_only': True,
            }
            self._publish_result(result)
            self._publish_debug(frame, state, warped, mask)
        except Exception as error:
            self.get_logger().error(f'Path-clearance processing failed: {error}')
            self._publish_result({'state': 'error', 'error': str(error)})


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = PathClearanceNode()
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
