"""Parser for the Yahboom 10-axis IMU 0x55 serial protocol.

The official Yahboom Raspberry Pi example uses fixed 11-byte frames:
  0x55, frame_type, 8 payload bytes, checksum

Supported frame types in this driver:
  0x51 acceleration
  0x52 angular velocity
  0x53 Euler orientation
  0x54 magnetic field (diagnostic/optional)

The checksum is the low byte of the sum of the first 10 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Iterable, Optional


FRAME_LENGTH = 11
FRAME_HEADER = 0x55
TYPE_ACCELERATION = 0x51
TYPE_GYROSCOPE = 0x52
TYPE_EULER = 0x53
TYPE_MAGNETIC = 0x54
SUPPORTED_TYPES = {
    TYPE_ACCELERATION,
    TYPE_GYROSCOPE,
    TYPE_EULER,
    TYPE_MAGNETIC,
}
STANDARD_GRAVITY = 9.80665


@dataclass(frozen=True)
class ParsedFrame:
    frame_type: int
    payload: bytes
    raw: bytes


def int16_le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def validate_frame(frame: bytes) -> bool:
    if len(frame) != FRAME_LENGTH:
        return False
    if frame[0] != FRAME_HEADER:
        return False
    if frame[1] not in SUPPORTED_TYPES:
        return False
    return (sum(frame[:10]) & 0xFF) == frame[10]


class YahboomFrameParser:
    """Incremental parser that resynchronizes after noise or partial frames."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.valid_frames = 0
        self.invalid_frames = 0
        self.discarded_bytes = 0

    def feed(self, data: bytes | bytearray) -> list[ParsedFrame]:
        if data:
            self._buffer.extend(data)

        frames: list[ParsedFrame] = []
        while True:
            try:
                header_index = self._buffer.index(FRAME_HEADER)
            except ValueError:
                self.discarded_bytes += len(self._buffer)
                self._buffer.clear()
                break

            if header_index:
                self.discarded_bytes += header_index
                del self._buffer[:header_index]

            if len(self._buffer) < FRAME_LENGTH:
                break

            candidate = bytes(self._buffer[:FRAME_LENGTH])
            if validate_frame(candidate):
                frames.append(
                    ParsedFrame(
                        frame_type=candidate[1],
                        payload=candidate[2:10],
                        raw=candidate,
                    )
                )
                self.valid_frames += 1
                del self._buffer[:FRAME_LENGTH]
            else:
                self.invalid_frames += 1
                self.discarded_bytes += 1
                del self._buffer[0]

        return frames


def decode_acceleration(payload: bytes) -> tuple[float, float, float]:
    """Return acceleration in m/s^2."""
    scale = 16.0 * STANDARD_GRAVITY / 32768.0
    return tuple(int16_le(payload, i) * scale for i in (0, 2, 4))  # type: ignore[return-value]


def decode_gyroscope(payload: bytes) -> tuple[float, float, float]:
    """Return angular velocity in rad/s."""
    scale = 2000.0 * math.pi / 180.0 / 32768.0
    return tuple(int16_le(payload, i) * scale for i in (0, 2, 4))  # type: ignore[return-value]


def decode_euler(payload: bytes) -> tuple[float, float, float]:
    """Return roll, pitch, yaw in radians."""
    scale = math.pi / 32768.0
    return tuple(int16_le(payload, i) * scale for i in (0, 2, 4))  # type: ignore[return-value]


def decode_magnetic_raw(payload: bytes) -> tuple[int, int, int]:
    """Return raw signed magnetometer channels."""
    return tuple(int16_le(payload, i) for i in (0, 2, 4))  # type: ignore[return-value]


def quaternion_from_euler(
    roll: float,
    pitch: float,
    yaw: float,
) -> tuple[float, float, float, float]:
    """ROS quaternion x, y, z, w from intrinsic roll/pitch/yaw."""
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)

    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    w = cr * cp * cy + sr * sp * sy
    norm = math.sqrt(x*x + y*y + z*z + w*w)
    if norm <= 1e-12:
        return 0.0, 0.0, 0.0, 1.0
    return x / norm, y / norm, z / norm, w / norm


def remap_vector(
    vector: tuple[float, float, float],
    axis_map: Iterable[int],
    axis_signs: Iterable[int],
) -> tuple[float, float, float]:
    mapping = tuple(int(value) for value in axis_map)
    signs = tuple(int(value) for value in axis_signs)
    if sorted(mapping) != [0, 1, 2]:
        raise ValueError("axis_map must be a permutation of [0, 1, 2]")
    if len(signs) != 3 or any(sign not in (-1, 1) for sign in signs):
        raise ValueError("axis_signs must contain three values, each +1 or -1")
    return tuple(vector[mapping[i]] * signs[i] for i in range(3))  # type: ignore[return-value]


def count_valid_frames(data: bytes) -> tuple[int, set[int]]:
    parser = YahboomFrameParser()
    types: set[int] = set()
    for frame in parser.feed(data):
        types.add(frame.frame_type)
    return parser.valid_frames, types
