from __future__ import annotations

import threading
import time
from typing import Iterable

import rclpy
from rclpy.node import Node
import serial
from serial import SerialException
from std_msgs.msg import String, UInt8

from rover_interfaces.msg import VoiceCommand
from rover_interfaces.srv import SpeakVoicePhrase


DEFAULT_HEADER = (0xAA, 0xFF)
DEFAULT_TAIL = 0xFB
DEFAULT_BROADCAST_TYPE = 0xFF


class VoiceFrameParser:
    """Parser for Yahboom fixed 5-byte ASR/TTS protocol frames."""

    def __init__(
        self,
        header: Iterable[int] = DEFAULT_HEADER,
        tail: int = DEFAULT_TAIL,
    ) -> None:
        self.header = bytes(int(value) & 0xFF for value in header)
        if len(self.header) != 2:
            raise ValueError('frame_header must contain exactly two bytes')
        self.tail = int(tail) & 0xFF
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        self._buffer.extend(data)

        while len(self._buffer) >= 5:
            if self._buffer[0] != self.header[0] or self._buffer[1] != self.header[1]:
                del self._buffer[0]
                continue

            if self._buffer[4] != self.tail:
                next_header = self._buffer.find(self.header, 1)
                if next_header >= 0:
                    del self._buffer[:next_header]
                else:
                    del self._buffer[0]
                continue

            frames.append(bytes(self._buffer[:5]))
            del self._buffer[:5]

        return frames


def parse_label_map(values: Iterable[str]) -> tuple[dict[int, str], dict[str, int]]:
    by_id: dict[int, str] = {}
    by_label: dict[str, int] = {}

    for raw_value in values:
        value = str(raw_value).strip()
        if not value or ':' not in value:
            continue

        raw_id, label = value.split(':', 1)
        label = label.strip()
        if not label:
            continue

        try:
            item_id = int(raw_id.strip(), 0)
        except ValueError:
            continue
        if item_id < 0 or item_id > 255:
            continue

        by_id[item_id] = label
        by_label[label] = item_id

    return by_id, by_label


def hex_frame(frame: bytes) -> str:
    return ' '.join(f'{value:02X}' for value in frame)


class VoiceModuleNode(Node):
    def __init__(self) -> None:
        super().__init__('voice_module_node')

        self.declare_parameter('serial_device', '/dev/myspeech')
        self.declare_parameter('baudrate', 115200)
        self.declare_parameter('read_timeout_sec', 0.1)
        self.declare_parameter('reconnect_interval_sec', 2.0)
        self.declare_parameter('command_topic', '/voice/command')
        self.declare_parameter('command_id_topic', '/voice/command_id')
        self.declare_parameter('raw_frame_topic', '/voice/raw_frame')
        self.declare_parameter('speak_id_topic', '/voice/speak_id')
        self.declare_parameter('speak_label_topic', '/voice/speak_label')
        self.declare_parameter('speak_phrase_service', '/voice/speak_phrase')
        self.declare_parameter('frame_header', list(DEFAULT_HEADER))
        self.declare_parameter('frame_tail', DEFAULT_TAIL)
        self.declare_parameter('broadcast_frame_type', DEFAULT_BROADCAST_TYPE)
        self.declare_parameter('command_labels', [''])
        self.declare_parameter('phrase_labels', [''])

        self.serial_device = str(self.get_parameter('serial_device').value).strip()
        self.baudrate = int(self.get_parameter('baudrate').value)
        self.read_timeout = max(
            0.02,
            float(self.get_parameter('read_timeout_sec').value),
        )
        self.reconnect_interval = max(
            0.2,
            float(self.get_parameter('reconnect_interval_sec').value),
        )
        self.frame_header = [
            int(value) & 0xFF
            for value in self.get_parameter('frame_header').value
        ]
        self.frame_tail = int(self.get_parameter('frame_tail').value) & 0xFF
        self.broadcast_frame_type = (
            int(self.get_parameter('broadcast_frame_type').value) & 0xFF
        )
        self.command_labels, _ = parse_label_map(
            self.get_parameter('command_labels').value
        )
        _, self.phrase_labels = parse_label_map(
            self.get_parameter('phrase_labels').value
        )

        if not self.serial_device:
            raise ValueError('serial_device must not be empty')
        if self.baudrate <= 0:
            raise ValueError('baudrate must be positive')

        self._parser = VoiceFrameParser(self.frame_header, self.frame_tail)
        self._serial: serial.Serial | None = None
        self._serial_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._connected = False
        self._last_connect_warning = 0.0

        self.command_pub = self.create_publisher(
            VoiceCommand,
            str(self.get_parameter('command_topic').value),
            10,
        )
        self.command_id_pub = self.create_publisher(
            UInt8,
            str(self.get_parameter('command_id_topic').value),
            10,
        )
        self.raw_frame_pub = self.create_publisher(
            String,
            str(self.get_parameter('raw_frame_topic').value),
            10,
        )
        self.create_subscription(
            UInt8,
            str(self.get_parameter('speak_id_topic').value),
            self._handle_speak_id,
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter('speak_label_topic').value),
            self._handle_speak_label,
            10,
        )
        self.create_service(
            SpeakVoicePhrase,
            str(self.get_parameter('speak_phrase_service').value),
            self._handle_speak_phrase,
        )

        self._reader_thread = threading.Thread(
            target=self._read_loop,
            name='voice-module-reader',
            daemon=True,
        )
        self._reader_thread.start()
        self.get_logger().info(
            f'Yahboom voice module driver started on {self.serial_device} '
            f'at {self.baudrate} baud'
        )

    def destroy_node(self):
        self._stop_event.set()
        if self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._close_serial()
        return super().destroy_node()

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                serial_port = self._ensure_serial()
                if serial_port is None:
                    self._stop_event.wait(self.reconnect_interval)
                    continue

                data = serial_port.read(64)
                if data:
                    for frame in self._parser.feed(data):
                        self._publish_frame(frame)
            except SerialException as exc:
                self.get_logger().warning(f'Voice module serial error: {exc}')
                self._close_serial()
                self._stop_event.wait(self.reconnect_interval)
            except Exception as exc:  # pragma: no cover - defensive guard
                self.get_logger().error(f'Voice module read loop error: {exc}')
                self._close_serial()
                self._stop_event.wait(self.reconnect_interval)

    def _ensure_serial(self) -> serial.Serial | None:
        with self._serial_lock:
            if self._serial is not None and self._serial.is_open:
                return self._serial

            try:
                self._serial = serial.Serial(
                    self.serial_device,
                    self.baudrate,
                    timeout=self.read_timeout,
                    write_timeout=0.5,
                )
                self._connected = True
                self.get_logger().info(
                    f'Connected to voice module at {self.serial_device}'
                )
                return self._serial
            except SerialException as exc:
                self._connected = False
                now = time.monotonic()
                if now - self._last_connect_warning >= 10.0:
                    self._last_connect_warning = now
                    self.get_logger().warning(
                        f'Waiting for voice module {self.serial_device}: {exc}'
                    )
                return None

    def _close_serial(self) -> None:
        with self._serial_lock:
            serial_port = self._serial
            self._serial = None
            self._connected = False

        if serial_port is not None:
            try:
                serial_port.close()
            except SerialException:
                pass

    def _publish_frame(self, frame: bytes) -> None:
        if len(frame) != 5:
            return

        frame_type = frame[2]
        command_id = frame[3]
        label = self.command_labels.get(command_id, '')

        message = VoiceCommand()
        message.header.stamp = self.get_clock().now().to_msg()
        message.frame_type = frame_type
        message.command_id = command_id
        message.label = label
        message.frame = list(frame)
        self.command_pub.publish(message)

        command_id_message = UInt8()
        command_id_message.data = command_id
        self.command_id_pub.publish(command_id_message)

        raw_message = String()
        raw_message.data = hex_frame(frame)
        self.raw_frame_pub.publish(raw_message)

        suffix = f' ({label})' if label else ''
        self.get_logger().info(
            f'Voice command frame={hex_frame(frame)} '
            f'type=0x{frame_type:02X} id={command_id}{suffix}'
        )

    def _handle_speak_id(self, message: UInt8) -> None:
        phrase_id = int(message.data) & 0xFF
        success, status = self._send_broadcast(phrase_id)
        if not success:
            self.get_logger().warning(status)

    def _handle_speak_label(self, message: String) -> None:
        label = message.data.strip()
        phrase_id = self._resolve_phrase(label, 0)
        if phrase_id is None:
            self.get_logger().warning(f'Unknown voice phrase label: {label}')
            return

        success, status = self._send_broadcast(phrase_id)
        if not success:
            self.get_logger().warning(status)

    def _handle_speak_phrase(
        self,
        request: SpeakVoicePhrase.Request,
        response: SpeakVoicePhrase.Response,
    ) -> SpeakVoicePhrase.Response:
        phrase_id = self._resolve_phrase(request.label, int(request.phrase_id))
        if phrase_id is None:
            response.success = False
            response.message = f'Unknown voice phrase label: {request.label}'
            return response

        response.success, response.message = self._send_broadcast(phrase_id)
        return response

    def _resolve_phrase(self, label: str, phrase_id: int) -> int | None:
        normalized_label = label.strip()
        if normalized_label:
            if normalized_label in self.phrase_labels:
                return self.phrase_labels[normalized_label]
            try:
                return int(normalized_label, 0) & 0xFF
            except ValueError:
                return None
        return phrase_id & 0xFF

    def _send_broadcast(self, phrase_id: int) -> tuple[bool, str]:
        frame = bytes((
            self.frame_header[0],
            self.frame_header[1],
            self.broadcast_frame_type,
            phrase_id & 0xFF,
            self.frame_tail,
        ))

        serial_port = self._ensure_serial()
        if serial_port is None:
            return False, f'Voice module is not connected at {self.serial_device}'

        try:
            with self._serial_lock:
                serial_port.write(frame)
                serial_port.flush()
        except SerialException as exc:
            self._close_serial()
            return False, f'Failed to write voice frame {hex_frame(frame)}: {exc}'

        return True, f'Sent voice phrase frame {hex_frame(frame)}'


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceModuleNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
