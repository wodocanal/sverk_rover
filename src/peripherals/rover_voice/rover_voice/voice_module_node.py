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


DEFAULT_RECEIVE_HEADER = (0xAA, 0x55)
DEFAULT_TRANSMIT_HEADER = (0xAA, 0xFF)
DEFAULT_TAIL = 0xFB
DEFAULT_BROADCAST_TYPE = 0xFF


class VoiceFrameParser:
    """Parser for Yahboom fixed 5-byte ASR/TTS protocol frames."""

    def __init__(
        self,
        header: Iterable[int] = DEFAULT_RECEIVE_HEADER,
        tail: int = DEFAULT_TAIL,
    ) -> None:
        self.header = bytes(int(value) & 0xFF for value in header)
        if len(self.header) != 2:
            raise ValueError('frame_header must contain exactly two bytes')
        self.tail = int(tail) & 0xFF
        self._buffer = bytearray()

    def is_idle(self) -> bool:
        return not self._buffer

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        self._buffer.extend(data)

        while self._buffer:
            if self._buffer[0] != self.header[0]:
                del self._buffer[0]
                continue
            if len(self._buffer) >= 2 and self._buffer[1] != self.header[1]:
                del self._buffer[0]
                continue
            break

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


def parse_command_label_map(
    values: Iterable[str],
) -> tuple[dict[int, str], dict[tuple[int, int], str]]:
    by_id: dict[int, str] = {}
    by_frame: dict[tuple[int, int], str] = {}

    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            continue

        parts = value.split(':')
        if len(parts) == 2:
            raw_id, label = parts
            try:
                command_id = int(raw_id.strip(), 0)
            except ValueError:
                continue
            label = label.strip()
            if 0 <= command_id <= 255 and label:
                by_id[command_id] = label
            continue

        if len(parts) >= 3:
            raw_type, raw_id = parts[0], parts[1]
            label = ':'.join(parts[2:]).strip()
            try:
                frame_type = int(raw_type.strip(), 0)
                command_id = int(raw_id.strip(), 0)
            except ValueError:
                continue
            if 0 <= frame_type <= 255 and 0 <= command_id <= 255 and label:
                by_frame[(frame_type, command_id)] = label

    return by_id, by_frame


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
        self.declare_parameter('raw_bytes_topic', '/voice/raw_bytes')
        self.declare_parameter('speak_id_topic', '/voice/speak_id')
        self.declare_parameter('speak_label_topic', '/voice/speak_label')
        self.declare_parameter('speak_phrase_service', '/voice/speak_phrase')
        self.declare_parameter('publish_raw_bytes', True)
        self.declare_parameter('single_byte_command_mode', True)
        self.declare_parameter('receive_frame_header', list(DEFAULT_RECEIVE_HEADER))
        self.declare_parameter('transmit_frame_header', list(DEFAULT_TRANSMIT_HEADER))
        self.declare_parameter('frame_header', list(DEFAULT_RECEIVE_HEADER))
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
        self.receive_frame_header = [
            int(value) & 0xFF
            for value in self.get_parameter('receive_frame_header').value
        ]
        self.transmit_frame_header = [
            int(value) & 0xFF
            for value in self.get_parameter('transmit_frame_header').value
        ]
        self.frame_tail = int(self.get_parameter('frame_tail').value) & 0xFF
        self.broadcast_frame_type = (
            int(self.get_parameter('broadcast_frame_type').value) & 0xFF
        )
        self.publish_raw_bytes = bool(
            self.get_parameter('publish_raw_bytes').value
        )
        self.single_byte_command_mode = bool(
            self.get_parameter('single_byte_command_mode').value
        )
        self.command_labels, self.command_frame_labels = parse_command_label_map(
            self.get_parameter('command_labels').value
        )
        _, self.phrase_labels = parse_label_map(
            self.get_parameter('phrase_labels').value
        )

        if not self.serial_device:
            raise ValueError('serial_device must not be empty')
        if self.baudrate <= 0:
            raise ValueError('baudrate must be positive')

        self._validate_header('receive_frame_header', self.receive_frame_header)
        self._validate_header('transmit_frame_header', self.transmit_frame_header)

        self._parser = VoiceFrameParser(self.receive_frame_header, self.frame_tail)
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
        self.raw_bytes_pub = self.create_publisher(
            String,
            str(self.get_parameter('raw_bytes_topic').value),
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
            f'at {self.baudrate} baud '
            f'(rx={hex_frame(bytes(self.receive_frame_header))}, '
            f'tx={hex_frame(bytes(self.transmit_frame_header))})'
        )

    def _validate_header(self, name: str, header: list[int]) -> None:
        if len(header) != 2:
            raise ValueError(f'{name} must contain exactly two bytes')

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
                    self._publish_raw_bytes(data)
                    if self._publish_single_byte_if_needed(data):
                        continue

                    frames = self._parser.feed(data)
                    for frame in frames:
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

        self._publish_command(frame[2], frame[3], frame)

    def _publish_raw_bytes(self, data: bytes) -> None:
        if not self.publish_raw_bytes:
            return

        raw_message = String()
        raw_message.data = hex_frame(data)
        self.raw_bytes_pub.publish(raw_message)

    def _publish_single_byte_if_needed(self, data: bytes) -> bool:
        if not self.single_byte_command_mode:
            return False
        if len(data) != 1 or not self._parser.is_idle():
            return False

        command_id = data[0]
        control_bytes = {
            self.receive_frame_header[0],
            self.receive_frame_header[1],
            self.transmit_frame_header[0],
            self.transmit_frame_header[1],
            self.frame_tail,
        }
        if command_id in control_bytes:
            return False

        self._publish_command(0x00, command_id, data)
        return True

    def _publish_command(self, frame_type: int, command_id: int, frame: bytes) -> None:
        normalized_type = frame_type & 0xFF
        normalized_id = command_id & 0xFF
        label = self.command_frame_labels.get(
            (normalized_type, normalized_id),
            self.command_labels.get(normalized_id, ''),
        )

        message = VoiceCommand()
        message.header.stamp = self.get_clock().now().to_msg()
        message.frame_type = normalized_type
        message.command_id = normalized_id
        message.label = label
        message.frame = list(frame)
        self.command_pub.publish(message)

        command_id_message = UInt8()
        command_id_message.data = normalized_id
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
            self.transmit_frame_header[0],
            self.transmit_frame_header[1],
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
