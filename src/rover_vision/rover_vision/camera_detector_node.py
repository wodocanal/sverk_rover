from __future__ import annotations

from dataclasses import dataclass
import math
import threading
from typing import Any, Optional

import cv2
import numpy as np
from rcl_interfaces.msg import SetParametersResult
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image

from rover_vision.model_registry import (
    ModelManifest,
    discover_model_manifests,
    resolve_models_directory,
)


@dataclass(slots=True)
class Detection:
    class_id: int
    label: str
    confidence: float
    x: int
    y: int
    width: int
    height: int


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def image_message_to_bgr(message: Image) -> np.ndarray:
    height = int(message.height)
    width = int(message.width)
    encoding = str(message.encoding).lower()
    if height <= 0 or width <= 0:
        raise ValueError('Image dimensions must be positive')

    buffer = np.frombuffer(message.data, dtype=np.uint8)
    if encoding in {'bgr8', 'rgb8'}:
        array = buffer.reshape((height, width, 3))
        if encoding == 'rgb8':
            return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
        return array.copy()
    if encoding in {'bgra8', 'rgba8'}:
        array = buffer.reshape((height, width, 4))
        if encoding == 'rgba8':
            return cv2.cvtColor(array, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(array, cv2.COLOR_BGRA2BGR)
    if encoding in {'mono8', '8uc1'}:
        array = buffer.reshape((height, width))
        return cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
    raise ValueError(f'Unsupported input encoding: {message.encoding}')


def encode_jpeg(frame: np.ndarray, quality: int) -> bytes:
    ok, encoded = cv2.imencode(
        '.jpg',
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
    )
    if not ok:
        raise RuntimeError('OpenCV could not encode annotated frame as JPEG')
    return encoded.tobytes()


class CameraDetectorNode(Node):
    def __init__(self) -> None:
        super().__init__('camera_detector_node')

        self.declare_parameter('enabled', False)
        self.declare_parameter('model_name', '')
        self.declare_parameter('models_directory', 'models')
        self.declare_parameter('input_topic', '/camera/image_raw')
        self.declare_parameter('processed_image_topic', '/camera/image_processed')
        self.declare_parameter(
            'processed_compressed_image_topic',
            '/camera/image_processed/compressed',
        )
        self.declare_parameter('frame_id', 'camera_optical_frame')
        self.declare_parameter('publish_raw', True)
        self.declare_parameter('publish_compressed', True)
        self.declare_parameter('confidence_threshold', 0.25)
        self.declare_parameter('nms_threshold', 0.45)
        self.declare_parameter('max_processing_fps', 8.0)
        self.declare_parameter('annotate_labels', True)
        self.declare_parameter('annotate_confidence', True)
        self.declare_parameter('line_thickness', 2)
        self.declare_parameter('jpeg_quality', 85)

        self._config_lock = threading.RLock()
        self._frame_lock = threading.RLock()
        self._subscription = None
        self._raw_publisher = None
        self._compressed_publisher = None
        self._timer = None

        self._net = None
        self._manifest: ModelManifest | None = None
        self._models_directory = resolve_models_directory('models')
        self._last_error = ''
        self._active = False

        self._latest_frame: np.ndarray | None = None
        self._latest_stamp = None
        self._latest_seq = 0
        self._last_processed_seq = 0

        self._frames_received = 0
        self._frames_processed = 0

        self._load_parameters()
        self.add_on_set_parameters_callback(self._handle_parameter_update)
        self._configure_timer()
        self._reconfigure_pipeline(initial=True)

    def _load_parameters(self) -> None:
        self.enabled = bool(self.get_parameter('enabled').value)
        self.model_name = str(self.get_parameter('model_name').value).strip()
        self.models_directory_text = str(
            self.get_parameter('models_directory').value
        ).strip() or 'models'
        self.input_topic = str(self.get_parameter('input_topic').value).strip()
        self.processed_image_topic = str(
            self.get_parameter('processed_image_topic').value
        ).strip()
        self.processed_compressed_image_topic = str(
            self.get_parameter('processed_compressed_image_topic').value
        ).strip()
        self.frame_id = str(self.get_parameter('frame_id').value).strip()
        self.publish_raw = bool(self.get_parameter('publish_raw').value)
        self.publish_compressed = bool(
            self.get_parameter('publish_compressed').value
        )
        self.confidence_threshold = float(
            self.get_parameter('confidence_threshold').value
        )
        self.nms_threshold = float(self.get_parameter('nms_threshold').value)
        self.max_processing_fps = float(
            self.get_parameter('max_processing_fps').value
        )
        self.annotate_labels = bool(
            self.get_parameter('annotate_labels').value
        )
        self.annotate_confidence = bool(
            self.get_parameter('annotate_confidence').value
        )
        self.line_thickness = int(self.get_parameter('line_thickness').value)
        self.jpeg_quality = int(self.get_parameter('jpeg_quality').value)
        self._validate_configuration()
        self._models_directory = resolve_models_directory(self.models_directory_text)

    def _validate_configuration(self) -> None:
        if not self.input_topic:
            raise ValueError('input_topic must not be empty')
        if not self.processed_image_topic:
            raise ValueError('processed_image_topic must not be empty')
        if not self.processed_compressed_image_topic:
            raise ValueError('processed_compressed_image_topic must not be empty')
        if not self.frame_id:
            raise ValueError('frame_id must not be empty')
        if not self.publish_raw and not self.publish_compressed:
            raise ValueError(
                'At least one of publish_raw or publish_compressed must be true'
            )
        if not math.isfinite(self.confidence_threshold):
            raise ValueError('confidence_threshold must be finite')
        if not math.isfinite(self.nms_threshold):
            raise ValueError('nms_threshold must be finite')
        if (
            not math.isfinite(self.max_processing_fps)
            or self.max_processing_fps <= 0.0
        ):
            raise ValueError('max_processing_fps must be finite and positive')
        if not 10 <= self.jpeg_quality <= 100:
            raise ValueError('jpeg_quality must be between 10 and 100')
        if self.line_thickness <= 0:
            raise ValueError('line_thickness must be positive')

    def _handle_parameter_update(
        self,
        parameters: list[Parameter],
    ) -> SetParametersResult:
        candidate = {
            'enabled': self.enabled,
            'model_name': self.model_name,
            'models_directory': self.models_directory_text,
            'input_topic': self.input_topic,
            'processed_image_topic': self.processed_image_topic,
            'processed_compressed_image_topic': self.processed_compressed_image_topic,
            'frame_id': self.frame_id,
            'publish_raw': self.publish_raw,
            'publish_compressed': self.publish_compressed,
            'confidence_threshold': self.confidence_threshold,
            'nms_threshold': self.nms_threshold,
            'max_processing_fps': self.max_processing_fps,
            'annotate_labels': self.annotate_labels,
            'annotate_confidence': self.annotate_confidence,
            'line_thickness': self.line_thickness,
            'jpeg_quality': self.jpeg_quality,
        }
        try:
            for parameter in parameters:
                if parameter.name in candidate:
                    candidate[parameter.name] = parameter.value

            self.enabled = bool(candidate['enabled'])
            self.model_name = str(candidate['model_name']).strip()
            self.models_directory_text = str(candidate['models_directory']).strip() or 'models'
            self.input_topic = str(candidate['input_topic']).strip()
            self.processed_image_topic = str(candidate['processed_image_topic']).strip()
            self.processed_compressed_image_topic = str(
                candidate['processed_compressed_image_topic']
            ).strip()
            self.frame_id = str(candidate['frame_id']).strip()
            self.publish_raw = bool(candidate['publish_raw'])
            self.publish_compressed = bool(candidate['publish_compressed'])
            self.confidence_threshold = float(candidate['confidence_threshold'])
            self.nms_threshold = float(candidate['nms_threshold'])
            self.max_processing_fps = float(candidate['max_processing_fps'])
            self.annotate_labels = bool(candidate['annotate_labels'])
            self.annotate_confidence = bool(candidate['annotate_confidence'])
            self.line_thickness = int(candidate['line_thickness'])
            self.jpeg_quality = int(candidate['jpeg_quality'])
            self._validate_configuration()
            self._models_directory = resolve_models_directory(self.models_directory_text)
        except (TypeError, ValueError) as exc:
            return SetParametersResult(successful=False, reason=str(exc))

        self._configure_timer()
        self._reconfigure_pipeline()
        return SetParametersResult(successful=True)

    def _configure_timer(self) -> None:
        if self._timer is not None:
            self.destroy_timer(self._timer)
        self._timer = self.create_timer(
            max(1.0 / self.max_processing_fps, 0.001),
            self._process_latest_frame,
        )

    def _destroy_io(self) -> None:
        if self._subscription is not None:
            self.destroy_subscription(self._subscription)
            self._subscription = None
        if self._raw_publisher is not None:
            self.destroy_publisher(self._raw_publisher)
            self._raw_publisher = None
        if self._compressed_publisher is not None:
            self.destroy_publisher(self._compressed_publisher)
            self._compressed_publisher = None

    def _find_selected_manifest(self) -> ModelManifest | None:
        manifests = discover_model_manifests(self._models_directory)
        for manifest in manifests:
            if manifest.identifier == self.model_name or manifest.display_name == self.model_name:
                return manifest
        return None

    def _load_model(self, manifest: ModelManifest) -> Any:
        if manifest.model_path is None:
            raise RuntimeError('Selected model does not define model_path')
        return cv2.dnn.readNet(str(manifest.model_path))

    def _reconfigure_pipeline(self, *, initial: bool = False) -> None:
        with self._config_lock:
            self._destroy_io()
            self._net = None
            self._manifest = None
            self._active = False
            self._last_error = ''

            if not self.enabled:
                if not initial:
                    self.get_logger().info('Camera detector disabled')
                return

            if not self.model_name:
                self._last_error = 'Model is not selected'
                self.get_logger().warning(self._last_error)
                return

            manifest = self._find_selected_manifest()
            if manifest is None:
                self._last_error = (
                    f'Selected model "{self.model_name}" was not found in {self._models_directory}'
                )
                self.get_logger().warning(self._last_error)
                return
            if not manifest.valid:
                self._last_error = manifest.error or 'Selected model manifest is invalid'
                self.get_logger().warning(self._last_error)
                return

            try:
                self._net = self._load_model(manifest)
            except Exception as exc:
                self._last_error = f'Could not load model {manifest.display_name}: {exc}'
                self.get_logger().error(self._last_error)
                return

            self._manifest = manifest
            self._subscription = self.create_subscription(
                Image,
                self.input_topic,
                self._image_callback,
                qos_profile_sensor_data,
            )
            if self.publish_raw:
                self._raw_publisher = self.create_publisher(
                    Image,
                    self.processed_image_topic,
                    qos_profile_sensor_data,
                )
            if self.publish_compressed:
                self._compressed_publisher = self.create_publisher(
                    CompressedImage,
                    self.processed_compressed_image_topic,
                    qos_profile_sensor_data,
                )
            self._active = True
            self.get_logger().info(
                'Camera detector enabled: '
                f'{manifest.display_name} ({manifest.model_format}) -> '
                f'{self.processed_image_topic}'
            )

    def _image_callback(self, message: Image) -> None:
        try:
            frame = image_message_to_bgr(message)
        except Exception as exc:
            self._last_error = str(exc)
            self.get_logger().warning(f'Camera detector skipped frame: {exc}')
            return

        with self._frame_lock:
            self._latest_frame = frame
            self._latest_stamp = message.header.stamp
            self._latest_seq += 1
            self._frames_received += 1

    def _should_process_now(self) -> bool:
        if not self._active or self._manifest is None or self._net is None:
            return False
        if (
            self._raw_publisher is not None
            and self._raw_publisher.get_subscription_count() > 0
        ):
            return True
        if (
            self._compressed_publisher is not None
            and self._compressed_publisher.get_subscription_count() > 0
        ):
            return True
        return False

    def _process_latest_frame(self) -> None:
        if not self._should_process_now():
            return

        with self._frame_lock:
            if (
                self._latest_seq <= 0
                or self._latest_seq == self._last_processed_seq
                or self._latest_frame is None
            ):
                return
            frame = self._latest_frame.copy()
            stamp = self._latest_stamp
            sequence = self._latest_seq

        try:
            annotated, detection_count = self._run_inference(frame)
        except Exception as exc:
            self._last_error = str(exc)
            self.get_logger().warning(f'Inference failed: {exc}')
            return

        self._publish_processed_frame(annotated, stamp)
        self._last_processed_seq = sequence
        self._frames_processed += 1
        if detection_count >= 0:
            self._last_error = ''

    def _run_inference(self, frame: np.ndarray) -> tuple[np.ndarray, int]:
        assert self._manifest is not None
        assert self._net is not None

        blob = cv2.dnn.blobFromImage(
            frame,
            scalefactor=1.0 / 255.0,
            size=(self._manifest.input_width, self._manifest.input_height),
            swapRB=self._manifest.swap_rb,
            crop=False,
        )
        self._net.setInput(blob)
        outputs = self._net.forward()
        detections = self._decode_detections(outputs, frame.shape[1], frame.shape[0])
        annotated = self._annotate_detections(frame, detections)
        return annotated, len(detections)

    def _decode_detections(
        self,
        outputs: Any,
        frame_width: int,
        frame_height: int,
    ) -> list[Detection]:
        assert self._manifest is not None

        prediction = np.array(outputs[0] if isinstance(outputs, (list, tuple)) else outputs)
        prediction = np.squeeze(prediction)
        if prediction.ndim == 1:
            prediction = prediction[np.newaxis, :]
        if prediction.ndim != 2:
            raise RuntimeError(f'Unsupported output shape: {prediction.shape}')

        if prediction.shape[0] < prediction.shape[1] and prediction.shape[0] <= 256:
            prediction = prediction.T

        boxes: list[list[int]] = []
        confidences: list[float] = []
        class_ids: list[int] = []
        labels: list[str] = []

        is_yolov5 = self._manifest.model_format == 'yolov5'
        class_offset = 5 if is_yolov5 else 4
        threshold = float(self.confidence_threshold)

        for row in prediction:
            if row.size <= class_offset:
                continue
            cx, cy, width, height = [float(value) for value in row[:4]]
            if is_yolov5:
                objectness = float(row[4])
                if objectness <= 0.0:
                    continue
                class_scores = row[5:]
                class_id = int(np.argmax(class_scores))
                class_confidence = float(class_scores[class_id])
                confidence = objectness * class_confidence
            else:
                class_scores = row[4:]
                class_id = int(np.argmax(class_scores))
                confidence = float(class_scores[class_id])

            if confidence < threshold:
                continue

            x, y, box_width, box_height = self._scale_box(
                cx,
                cy,
                width,
                height,
                frame_width,
                frame_height,
            )
            boxes.append([x, y, box_width, box_height])
            confidences.append(confidence)
            class_ids.append(class_id)
            labels.append(self._label_for_class(class_id, class_scores.size))

        if not boxes:
            return []

        indices = cv2.dnn.NMSBoxes(
            boxes,
            confidences,
            float(max(0.01, self.confidence_threshold)),
            float(max(0.01, self.nms_threshold)),
        )
        if len(indices) == 0:
            return []

        flat_indices = np.array(indices).reshape(-1).tolist()
        detections: list[Detection] = []
        for index in flat_indices:
            x, y, width, height = boxes[index]
            detections.append(Detection(
                class_id=class_ids[index],
                label=labels[index],
                confidence=confidences[index],
                x=x,
                y=y,
                width=width,
                height=height,
            ))
        return detections

    def _label_for_class(self, class_id: int, class_count: int) -> str:
        assert self._manifest is not None
        labels = self._manifest.labels
        if 0 <= class_id < len(labels):
            return labels[class_id]
        return f'class_{class_id}'

    def _scale_box(
        self,
        cx: float,
        cy: float,
        width: float,
        height: float,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int, int, int]:
        assert self._manifest is not None

        max_coord = max(abs(cx), abs(cy), abs(width), abs(height))
        if max_coord <= 2.0:
            x = (cx - width / 2.0) * frame_width
            y = (cy - height / 2.0) * frame_height
            box_width = width * frame_width
            box_height = height * frame_height
        else:
            x_factor = frame_width / float(self._manifest.input_width)
            y_factor = frame_height / float(self._manifest.input_height)
            x = (cx - width / 2.0) * x_factor
            y = (cy - height / 2.0) * y_factor
            box_width = width * x_factor
            box_height = height * y_factor

        x_int = clamp_int(round(x), 0, max(0, frame_width - 1))
        y_int = clamp_int(round(y), 0, max(0, frame_height - 1))
        width_int = clamp_int(round(box_width), 1, frame_width)
        height_int = clamp_int(round(box_height), 1, frame_height)
        if x_int + width_int > frame_width:
            width_int = max(1, frame_width - x_int)
        if y_int + height_int > frame_height:
            height_int = max(1, frame_height - y_int)
        return x_int, y_int, width_int, height_int

    def _annotate_detections(
        self,
        frame: np.ndarray,
        detections: list[Detection],
    ) -> np.ndarray:
        annotated = frame.copy()
        for detection in detections:
            color = self._color_for_class(detection.class_id)
            x1 = detection.x
            y1 = detection.y
            x2 = detection.x + detection.width
            y2 = detection.y + detection.height
            cv2.rectangle(
                annotated,
                (x1, y1),
                (x2, y2),
                color,
                int(self.line_thickness),
            )

            text_parts: list[str] = []
            if self.annotate_labels:
                text_parts.append(detection.label)
            if self.annotate_confidence:
                text_parts.append(f'{detection.confidence:.2f}')
            if text_parts:
                text = ' '.join(text_parts)
                (text_width, text_height), baseline = cv2.getTextSize(
                    text,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    1,
                )
                text_top = max(0, y1 - text_height - baseline - 6)
                cv2.rectangle(
                    annotated,
                    (x1, text_top),
                    (x1 + text_width + 8, text_top + text_height + baseline + 6),
                    color,
                    -1,
                )
                cv2.putText(
                    annotated,
                    text,
                    (x1 + 4, text_top + text_height + 1),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
        return annotated

    def _color_for_class(self, class_id: int) -> tuple[int, int, int]:
        hue = (class_id * 37) % 180
        hsv = np.uint8([[[hue, 220, 255]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0]
        return int(bgr[0]), int(bgr[1]), int(bgr[2])

    def _publish_processed_frame(self, frame: np.ndarray, stamp: Any) -> None:
        height, width = frame.shape[:2]
        if self._raw_publisher is not None:
            message = Image()
            message.header.stamp = stamp
            message.header.frame_id = self.frame_id
            message.height = int(height)
            message.width = int(width)
            message.encoding = 'bgr8'
            message.is_bigendian = False
            message.step = int(width * 3)
            message.data = frame.tobytes()
            self._raw_publisher.publish(message)

        if self._compressed_publisher is not None:
            data = encode_jpeg(frame, self.jpeg_quality)
            message = CompressedImage()
            message.header.stamp = stamp
            message.header.frame_id = self.frame_id
            message.format = 'jpeg'
            message.data = data
            self._compressed_publisher.publish(message)

    def close(self) -> None:
        self._destroy_io()
        if self._timer is not None:
            self.destroy_timer(self._timer)
            self._timer = None


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node: CameraDetectorNode | None = None
    try:
        node = CameraDetectorNode()
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
