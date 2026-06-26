from __future__ import annotations

import colorsys
import math
import time
from typing import Iterable

from rcl_interfaces.msg import SetParametersResult
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter as RosParameter
from rover_interfaces.msg import LedStripState
from rover_interfaces.srv import SetLedStripState

from rover_led_strip.led_backend import BackendUnavailableError, LedStripBackend


SUPPORTED_EFFECTS = (
    'solid',
    'blink',
    'pulse',
    'chase',
    'gradient',
    'rainbow',
)
READ_ONLY_PARAMETER_NAMES = {'state_topic', 'set_state_service'}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def clamp_byte(value: int | float) -> int:
    return max(0, min(255, int(round(float(value)))))


def parse_color_text(text: str) -> tuple[int, int, int]:
    raw = str(text).strip().lstrip('#')
    if len(raw) != 6:
        raise ValueError('Color must be in #RRGGBB format')
    return (
        int(raw[0:2], 16),
        int(raw[2:4], 16),
        int(raw[4:6], 16),
    )


def color_to_hex(color: tuple[int, int, int]) -> str:
    return '#%02X%02X%02X' % tuple(clamp_byte(channel) for channel in color)


def pack_color(color: tuple[int, int, int]) -> int:
    red, green, blue = (clamp_byte(channel) for channel in color)
    return (red << 16) | (green << 8) | blue


def scale_color(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    gain = clamp(factor, 0.0, 1.0)
    return tuple(clamp_byte(channel * gain) for channel in color)


def mix_color(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    ratio: float,
) -> tuple[int, int, int]:
    amount = clamp(ratio, 0.0, 1.0)
    return tuple(
        clamp_byte(left[index] + (right[index] - left[index]) * amount)
        for index in range(3)
    )


def rainbow_color(position: float) -> tuple[int, int, int]:
    hue = position % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return (
        clamp_byte(red * 255.0),
        clamp_byte(green * 255.0),
        clamp_byte(blue * 255.0),
    )


def validate_pixel_order(value: str) -> str:
    text = str(value).strip().upper()
    if len(text) != 3 or set(text) != {'R', 'G', 'B'}:
        raise ValueError('pixel_order must be a permutation of RGB, for example GRB')
    return text


class LedStripNode(Node):
    def __init__(self) -> None:
        super().__init__('led_strip_node')

        self.declare_parameter('gpio_pin', 18)
        self.declare_parameter('led_count', 16)
        self.declare_parameter('frame_id', 'led_strip')
        self.declare_parameter('pixel_order', 'GRB')
        self.declare_parameter('state_topic', '/led_strip/state')
        self.declare_parameter('set_state_service', '/led_strip/set_state')
        self.declare_parameter('enabled', False)
        self.declare_parameter('brightness', 0.35)
        self.declare_parameter('effect', 'solid')
        self.declare_parameter('effect_speed_hz', 1.0)
        self.declare_parameter('primary_color', '#16B8F3')
        self.declare_parameter('secondary_color', '#FFFFFF')
        self.declare_parameter('animation_rate_hz', 30.0)
        self.declare_parameter('state_publish_hz', 5.0)

        self._settings = self._current_settings_from_parameters()
        self._backend: LedStripBackend | None = None
        self._backend_name = 'software-preview'
        self._backend_error = ''
        self._preview_colors: list[tuple[int, int, int]] = []
        self._last_render_signature: tuple[int, ...] | None = None

        self._state_publisher = self.create_publisher(
            LedStripState,
            str(self.get_parameter('state_topic').value),
            10,
        )
        self.create_service(
            SetLedStripState,
            str(self.get_parameter('set_state_service').value),
            self._handle_set_state,
        )
        self.add_on_set_parameters_callback(self._on_parameter_set)

        self._animation_timer = self.create_timer(
            1.0 / max(1.0, float(self._settings['animation_rate_hz'])),
            self._animation_tick,
        )
        self._state_timer = self.create_timer(
            1.0 / max(0.5, float(self._settings['state_publish_hz'])),
            self._publish_state,
        )

        self._configure_backend(self._settings)
        self._render_and_show(force=True)
        self.get_logger().info(
            'LED strip node ready on GPIO %d with %d LEDs (%s)'
            % (
                int(self._settings['gpio_pin']),
                int(self._settings['led_count']),
                self._settings['pixel_order'],
            )
        )

    def _current_settings_from_parameters(self) -> dict[str, object]:
        return {
            'gpio_pin': int(self.get_parameter('gpio_pin').value),
            'led_count': int(self.get_parameter('led_count').value),
            'frame_id': str(self.get_parameter('frame_id').value),
            'pixel_order': validate_pixel_order(
                str(self.get_parameter('pixel_order').value)
            ),
            'state_topic': str(self.get_parameter('state_topic').value),
            'set_state_service': str(self.get_parameter('set_state_service').value),
            'enabled': bool(self.get_parameter('enabled').value),
            'brightness': clamp(self.get_parameter('brightness').value, 0.0, 1.0),
            'effect': str(self.get_parameter('effect').value).strip().lower(),
            'effect_speed_hz': clamp(
                self.get_parameter('effect_speed_hz').value,
                0.05,
                20.0,
            ),
            'primary_color': str(self.get_parameter('primary_color').value).strip(),
            'secondary_color': str(
                self.get_parameter('secondary_color').value
            ).strip(),
            'animation_rate_hz': clamp(
                self.get_parameter('animation_rate_hz').value,
                1.0,
                120.0,
            ),
            'state_publish_hz': clamp(
                self.get_parameter('state_publish_hz').value,
                0.5,
                30.0,
            ),
        }

    def _validate_settings(self, settings: dict[str, object]) -> dict[str, object]:
        validated = dict(settings)
        validated['gpio_pin'] = int(validated['gpio_pin'])
        validated['led_count'] = int(validated['led_count'])
        if validated['gpio_pin'] < 0 or validated['gpio_pin'] > 27:
            raise ValueError('gpio_pin must be between 0 and 27')
        if validated['led_count'] < 1 or validated['led_count'] > 1024:
            raise ValueError('led_count must be between 1 and 1024')
        validated['frame_id'] = str(validated['frame_id']).strip() or 'led_strip'
        validated['pixel_order'] = validate_pixel_order(validated['pixel_order'])
        validated['brightness'] = clamp(validated['brightness'], 0.0, 1.0)
        effect = str(validated['effect']).strip().lower()
        if effect not in SUPPORTED_EFFECTS:
            raise ValueError(
                f'Unsupported effect {effect!r}. Supported: {", ".join(SUPPORTED_EFFECTS)}'
            )
        validated['effect'] = effect
        validated['effect_speed_hz'] = clamp(validated['effect_speed_hz'], 0.05, 20.0)
        validated['primary_color'] = color_to_hex(parse_color_text(validated['primary_color']))
        validated['secondary_color'] = color_to_hex(
            parse_color_text(validated['secondary_color'])
        )
        validated['animation_rate_hz'] = clamp(validated['animation_rate_hz'], 1.0, 120.0)
        validated['state_publish_hz'] = clamp(validated['state_publish_hz'], 0.5, 30.0)
        validated['enabled'] = bool(validated['enabled'])
        validated['state_topic'] = str(validated['state_topic']).strip() or '/led_strip/state'
        validated['set_state_service'] = (
            str(validated['set_state_service']).strip() or '/led_strip/set_state'
        )
        return validated

    def _on_parameter_set(self, parameters):
        try:
            candidate = dict(self._settings)
            for parameter in parameters:
                if parameter.name in READ_ONLY_PARAMETER_NAMES:
                    current_value = self._settings[parameter.name]
                    if parameter.value != current_value:
                        raise ValueError(
                            f'{parameter.name} requires node restart to change'
                        )
                    continue
                candidate[parameter.name] = parameter.value

            validated = self._validate_settings(candidate)
            self._apply_settings(validated)
        except Exception as exc:
            return SetParametersResult(successful=False, reason=str(exc))
        return SetParametersResult(successful=True)

    def _configure_backend(self, settings: dict[str, object]) -> None:
        previous = self._backend
        self._backend = None
        self._backend_name = 'software-preview'
        self._backend_error = ''

        try:
            self._backend = LedStripBackend(
                gpio_pin=int(settings['gpio_pin']),
                led_count=int(settings['led_count']),
                pixel_order=str(settings['pixel_order']),
            )
            self._backend_name = self._backend.info.name
        except BackendUnavailableError as exc:
            self._backend_error = str(exc)
            self.get_logger().warning(self._backend_error)
        except Exception as exc:  # pragma: no cover - hardware-specific failure
            self._backend_error = f'Failed to initialize LED strip backend: {exc}'
            self.get_logger().error(self._backend_error)
        finally:
            if previous is not None and previous is not self._backend:
                try:
                    previous.clear()
                except Exception:
                    pass

    def _recreate_animation_timer(self, rate_hz: float) -> None:
        self._animation_timer.cancel()
        self._animation_timer = self.create_timer(
            1.0 / max(1.0, float(rate_hz)),
            self._animation_tick,
        )

    def _recreate_state_timer(self, rate_hz: float) -> None:
        self._state_timer.cancel()
        self._state_timer = self.create_timer(
            1.0 / max(0.5, float(rate_hz)),
            self._publish_state,
        )

    def _apply_settings(self, settings: dict[str, object]) -> None:
        previous = dict(self._settings)
        self._settings = dict(settings)

        if any(
            previous.get(name) != settings.get(name)
            for name in ('gpio_pin', 'led_count', 'pixel_order')
        ):
            self._configure_backend(settings)

        if previous.get('animation_rate_hz') != settings.get('animation_rate_hz'):
            self._recreate_animation_timer(float(settings['animation_rate_hz']))

        if previous.get('state_publish_hz') != settings.get('state_publish_hz'):
            self._recreate_state_timer(float(settings['state_publish_hz']))

        self._render_and_show(force=True)

    def _primary_color(self) -> tuple[int, int, int]:
        return parse_color_text(self._settings['primary_color'])

    def _secondary_color(self) -> tuple[int, int, int]:
        return parse_color_text(self._settings['secondary_color'])

    def _effect_frame(self, now: float) -> list[tuple[int, int, int]]:
        count = int(self._settings['led_count'])
        if count <= 0:
            return []

        if not bool(self._settings['enabled']):
            return [(0, 0, 0)] * count

        primary = self._primary_color()
        secondary = self._secondary_color()
        effect = str(self._settings['effect'])
        speed = float(self._settings['effect_speed_hz'])
        phase = now * speed

        if effect == 'solid':
            return [primary] * count

        if effect == 'blink':
            visible = int(math.floor(phase)) % 2 == 0
            return [primary if visible else (0, 0, 0)] * count

        if effect == 'pulse':
            gain = 0.18 + 0.82 * ((math.sin(phase * math.tau) + 1.0) / 2.0)
            return [scale_color(primary, gain)] * count

        if effect == 'chase':
            tail = max(1, min(5, count // 6 or 1))
            head = int(math.floor(phase * max(1, count / 6.0))) % count
            frame = [scale_color(secondary, 0.08)] * count
            for offset in range(tail):
                index = (head + offset) % count
                gain = 1.0 - (offset / max(1, tail))
                frame[index] = mix_color(secondary, primary, gain)
            return frame

        if effect == 'gradient':
            if count == 1:
                return [primary]
            return [
                mix_color(primary, secondary, index / (count - 1))
                for index in range(count)
            ]

        if effect == 'rainbow':
            shift = (phase * 0.12) % 1.0
            return [
                rainbow_color((index / max(1, count)) + shift)
                for index in range(count)
            ]

        return [primary] * count

    def _render_and_show(self, *, force: bool = False) -> None:
        frame = self._effect_frame(time.monotonic())
        signature = tuple(pack_color(color) for color in frame)
        self._preview_colors = frame
        if not force and signature == self._last_render_signature:
            return
        self._last_render_signature = signature

        if self._backend is not None:
            try:
                self._backend.show(
                    frame,
                    brightness=float(self._settings['brightness']),
                )
                self._backend_error = ''
            except Exception as exc:  # pragma: no cover - hardware-specific failure
                self._backend_error = f'LED output failed: {exc}'
                self.get_logger().warning(
                    self._backend_error,
                    throttle_duration_sec=2.0,
                )

    def _animation_tick(self) -> None:
        self._render_and_show()

    def _publish_state(self) -> None:
        message = LedStripState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = str(self._settings['frame_id'])
        message.connected = self._backend is not None and not self._backend_error
        message.enabled = bool(self._settings['enabled'])
        message.led_count = int(self._settings['led_count'])
        message.lit_count = sum(
            1 for color in self._preview_colors if any(channel > 0 for channel in color)
        )
        message.brightness = float(self._settings['brightness'])
        message.effect = str(self._settings['effect'])
        message.effect_speed_hz = float(self._settings['effect_speed_hz'])
        message.gpio_pin = int(self._settings['gpio_pin'])
        message.pixel_order = str(self._settings['pixel_order'])
        message.backend = self._backend_name
        if message.connected:
            message.status_message = 'LED strip is active.'
        else:
            message.status_message = (
                self._backend_error or 'LED strip preview mode only.'
            )
        primary = self._primary_color()
        secondary = self._secondary_color()
        message.red, message.green, message.blue = primary
        (
            message.secondary_red,
            message.secondary_green,
            message.secondary_blue,
        ) = secondary
        message.preview_colors = [pack_color(color) for color in self._preview_colors]
        self._state_publisher.publish(message)

    def _command_parameters_from_request(
        self,
        request: SetLedStripState.Request,
    ) -> list[RosParameter]:
        return [
            RosParameter('enabled', value=bool(request.enabled)),
            RosParameter('brightness', value=float(request.brightness)),
            RosParameter('effect', value=str(request.effect).strip().lower()),
            RosParameter('effect_speed_hz', value=float(request.effect_speed_hz)),
            RosParameter(
                'primary_color',
                value=color_to_hex((request.red, request.green, request.blue)),
            ),
            RosParameter(
                'secondary_color',
                value=color_to_hex(
                    (
                        request.secondary_red,
                        request.secondary_green,
                        request.secondary_blue,
                    )
                ),
            ),
        ]

    def _handle_set_state(self, request, response):
        try:
            results = self.set_parameters(self._command_parameters_from_request(request))
            failures = [
                result.reason.strip() or 'parameter update rejected'
                for result in results
                if not result.successful
            ]
            if failures:
                raise RuntimeError('; '.join(failures))
        except Exception as exc:
            response.success = False
            response.message = f'Failed to update LED strip: {exc}'
            return response

        response.success = True
        response.message = (
            f"LED strip set to {self._settings['effect']} at "
            f"{float(self._settings['brightness']):.2f} brightness"
        )
        self._publish_state()
        return response


def main(args: Iterable[str] | None = None) -> None:
    rclpy.init(args=args)
    node: LedStripNode | None = None
    try:
        node = LedStripNode()
        rclpy.spin(node)
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
