"""Terminal keyboard teleoperation for the rover's mecanum base."""

from __future__ import annotations

import math
import os
import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


HELP_TEXT = """
Mecanum keyboard control
------------------------
  W / S : forward / backward
  A / D : strafe left / right
  Q / E : rotate counter-clockwise / clockwise
  Space : immediate stop
  + / - : increase / decrease all speed presets
  H     : print this help again
  X     : stop and exit

The command is automatically reset to zero when no movement key has been
received within the configured timeout. Keep the terminal focused while moving.
""".strip()


@dataclass(frozen=True)
class VelocityCommand:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class MecanumKeyboardNode(Node):
    """Publish safe body-frame velocity commands from terminal key presses."""

    def __init__(self, default_topic: str = '/cmd_vel') -> None:
        super().__init__('mecanum_keyboard')

        self.declare_parameter('cmd_vel_topic', default_topic)
        self.declare_parameter('forward_speed_mps', 0.15)
        self.declare_parameter('lateral_speed_mps', 0.12)
        self.declare_parameter('angular_speed_radps', 0.40)
        self.declare_parameter('speed_step_fraction', 0.10)
        self.declare_parameter('minimum_speed_scale', 0.40)
        self.declare_parameter('maximum_speed_scale', 1.50)
        self.declare_parameter('key_timeout_sec', 0.45)
        self.declare_parameter('publish_rate_hz', 20.0)

        self._topic = str(self.get_parameter('cmd_vel_topic').value)
        self._forward_speed = self._positive_finite(
            'forward_speed_mps',
            self.get_parameter('forward_speed_mps').value,
        )
        self._lateral_speed = self._positive_finite(
            'lateral_speed_mps',
            self.get_parameter('lateral_speed_mps').value,
        )
        self._angular_speed = self._positive_finite(
            'angular_speed_radps',
            self.get_parameter('angular_speed_radps').value,
        )
        self._speed_step = self._positive_finite(
            'speed_step_fraction',
            self.get_parameter('speed_step_fraction').value,
        )
        self._minimum_scale = self._positive_finite(
            'minimum_speed_scale',
            self.get_parameter('minimum_speed_scale').value,
        )
        self._maximum_scale = self._positive_finite(
            'maximum_speed_scale',
            self.get_parameter('maximum_speed_scale').value,
        )
        self._key_timeout = self._positive_finite(
            'key_timeout_sec',
            self.get_parameter('key_timeout_sec').value,
        )
        publish_rate = self._positive_finite(
            'publish_rate_hz',
            self.get_parameter('publish_rate_hz').value,
        )

        if self._minimum_scale > self._maximum_scale:
            raise ValueError(
                'minimum_speed_scale must not exceed maximum_speed_scale'
            )

        self._publisher = self.create_publisher(Twist, self._topic, 10)
        self._command = VelocityCommand()
        self._last_motion_key_time: Optional[float] = None
        self._speed_scale = 1.0
        self._zero_was_published = True
        self._exit_requested = False

        self.create_timer(1.0 / publish_rate, self._publish_timer)

        self.get_logger().info(
            f'Keyboard teleop publishes to {self._topic}; '
            f'x={self._forward_speed:.2f} m/s, '
            f'y={self._lateral_speed:.2f} m/s, '
            f'z={self._angular_speed:.2f} rad/s; '
            f'timeout={self._key_timeout:.2f} s'
        )

    @staticmethod
    def _positive_finite(name: str, value: object) -> float:
        result = float(value)
        if not math.isfinite(result) or result <= 0.0:
            raise ValueError(f'{name} must be finite and positive')
        return result

    @property
    def exit_requested(self) -> bool:
        return self._exit_requested

    def handle_key(self, key: str) -> None:
        normalized = key.lower()
        now = time.monotonic()

        commands = {
            'w': VelocityCommand(x=self._forward_speed),
            's': VelocityCommand(x=-self._forward_speed),
            'a': VelocityCommand(y=self._lateral_speed),
            'd': VelocityCommand(y=-self._lateral_speed),
            'q': VelocityCommand(z=self._angular_speed),
            'e': VelocityCommand(z=-self._angular_speed),
        }

        if normalized in commands:
            base = commands[normalized]
            self._command = VelocityCommand(
                x=base.x * self._speed_scale,
                y=base.y * self._speed_scale,
                z=base.z * self._speed_scale,
            )
            self._last_motion_key_time = now
            self._zero_was_published = False
            return

        if key == ' ':
            self.stop()
            return

        if normalized in ('+', '='):
            self._set_speed_scale(self._speed_scale + self._speed_step)
            return

        if normalized in ('-', '_'):
            self._set_speed_scale(self._speed_scale - self._speed_step)
            return

        if normalized == 'h':
            print('\n' + HELP_TEXT + '\n', flush=True)
            return

        if normalized in ('x', '\x03'):
            self.stop()
            self._exit_requested = True

    def _set_speed_scale(self, requested: float) -> None:
        self._speed_scale = min(
            self._maximum_scale,
            max(self._minimum_scale, requested),
        )
        self.stop()
        self.get_logger().info(
            f'Speed scale: {self._speed_scale:.0%}; '
            f'x={self._forward_speed * self._speed_scale:.2f} m/s, '
            f'y={self._lateral_speed * self._speed_scale:.2f} m/s, '
            f'z={self._angular_speed * self._speed_scale:.2f} rad/s'
        )

    def stop(self) -> None:
        self._command = VelocityCommand()
        self._last_motion_key_time = None
        self._publish(self._command)
        self._zero_was_published = True

    def _publish_timer(self) -> None:
        if self._last_motion_key_time is not None:
            age = time.monotonic() - self._last_motion_key_time
            if age > self._key_timeout:
                self._command = VelocityCommand()
                self._last_motion_key_time = None

        is_zero = self._command == VelocityCommand()
        if not is_zero or not self._zero_was_published:
            self._publish(self._command)
        self._zero_was_published = is_zero

    def _publish(self, command: VelocityCommand) -> None:
        message = Twist()
        message.linear.x = command.x
        message.linear.y = command.y
        message.angular.z = command.z
        self._publisher.publish(message)


class RawTerminal:
    """Restore terminal settings even after exceptions or Ctrl+C."""

    def __init__(self, stream) -> None:
        self._stream = stream
        self._fd = stream.fileno()
        self._original = None

    def __enter__(self):
        if not os.isatty(self._fd):
            raise RuntimeError(
                'rover_teleop requires an interactive terminal (TTY)'
            )
        self._original = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._original is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original)

    def read_key(self, timeout_sec: float) -> Optional[str]:
        ready, _, _ = select.select([self._stream], [], [], timeout_sec)
        if not ready:
            return None
        return self._stream.read(1)


def _run(default_topic: str, args=None) -> None:
    rclpy.init(args=args)
    node: Optional[MecanumKeyboardNode] = None

    try:
        node = MecanumKeyboardNode(default_topic=default_topic)
        print('\n' + HELP_TEXT + '\n', flush=True)

        with RawTerminal(sys.stdin) as terminal:
            while rclpy.ok() and not node.exit_requested:
                key = terminal.read_key(0.02)
                if key is not None:
                    node.handle_key(key)
                rclpy.spin_once(node, timeout_sec=0.0)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if node is not None:
            node.get_logger().error(str(exc))
        else:
            print(f'rover_teleop error: {exc}', file=sys.stderr)
    finally:
        if node is not None:
            # Publish several zeros so the serial driver sees an immediate stop
            # before its independent command watchdog becomes necessary.
            for _ in range(3):
                node.stop()
                rclpy.spin_once(node, timeout_sec=0.02)
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main(args=None) -> None:
    """Publish directly to /cmd_vel for manual mapping and testing."""
    _run('/cmd_vel', args=args)


def main_mux(args=None) -> None:
    """Publish to the high-priority twist_mux teleop input."""
    _run('/cmd_vel_teleop', args=args)


if __name__ == '__main__':
    main()
