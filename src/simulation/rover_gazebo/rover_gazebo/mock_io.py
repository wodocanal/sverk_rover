from __future__ import annotations

from typing import Optional

from rcl_interfaces.msg import SetParametersResult
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Float32

from rover_interfaces.msg import LEDState, LEDStateArray, LedStripState
from rover_interfaces.srv import SetLEDEffect, SetLEDs, SetLedStripState


class MockIo(Node):
    def __init__(self) -> None:
        super().__init__('led_strip_node')
        defaults = {
            'led_transport': 'simulation',
            'spi_bus': 0,
            'spi_device': 0,
            'led_count': 16,
            'frame_id': 'led_strip',
            'state_topic': '/led_strip/state',
            'set_state_service': '/led_strip/set_state',
            'native_state_topic': '/led/state',
            'set_effect_service': '/led/set_effect',
            'set_leds_service': '/led/set_leds',
            'enabled': False,
            'brightness': 0.35,
            'effect': 'fill',
            'effect_speed_hz': 1.0,
            'primary_color': '#16B8F3',
            'secondary_color': '#FFFFFF',
            'pixel_order': 'GRB',
            'gpio_pin': 18,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        self.manual_leds: list[LEDState] = []
        self.compat_publisher = self.create_publisher(
            LedStripState, '/led_strip/state', 10
        )
        self.native_publisher = self.create_publisher(LEDStateArray, '/led/state', 10)
        self.voltage_publisher = self.create_publisher(Float32, '/battery_voltage', 10)
        self.battery_publisher = self.create_publisher(BatteryState, '/battery/state', 10)
        self.create_service(SetLedStripState, '/led_strip/set_state', self._set_state)
        self.create_service(SetLEDEffect, '/led/set_effect', self._set_effect)
        self.create_service(SetLEDs, '/led/set_leds', self._set_leds)
        self.add_on_set_parameters_callback(
            lambda _params: SetParametersResult(successful=True)
        )
        self.timer = self.create_timer(0.2, self._publish)

    @staticmethod
    def _hex(red: int, green: int, blue: int) -> str:
        return f'#{red:02X}{green:02X}{blue:02X}'

    def _set_state(self, request, response):
        self.set_parameters([
            Parameter('enabled', value=bool(request.enabled)),
            Parameter('brightness', value=float(request.brightness)),
            Parameter('effect', value=str(request.effect)),
            Parameter('effect_speed_hz', value=float(request.effect_speed_hz)),
            Parameter(
                'primary_color', value=self._hex(request.red, request.green, request.blue)
            ),
            Parameter(
                'secondary_color',
                value=self._hex(
                    request.secondary_red, request.secondary_green, request.secondary_blue
                ),
            ),
        ])
        response.success = True
        response.message = 'Simulated LED strip state updated'
        return response

    def _set_effect(self, request, response):
        self.set_parameters([
            Parameter('enabled', value=True),
            Parameter('effect', value=str(request.effect)),
            Parameter(
                'primary_color', value=self._hex(request.r, request.g, request.b)
            ),
        ])
        response.success = True
        return response

    def _set_leds(self, request, response):
        self.manual_leds = list(request.leds)
        response.success = True
        return response

    def _publish(self) -> None:
        voltage = Float32()
        voltage.data = 12.3
        self.voltage_publisher.publish(voltage)
        battery = BatteryState()
        battery.header.stamp = self.get_clock().now().to_msg()
        battery.voltage = 12.3
        battery.percentage = 0.82
        battery.present = True
        self.battery_publisher.publish(battery)

        primary = str(self.get_parameter('primary_color').value).lstrip('#')
        secondary = str(self.get_parameter('secondary_color').value).lstrip('#')
        primary_rgb = tuple(int(primary[index:index + 2], 16) for index in (0, 2, 4))
        secondary_rgb = tuple(int(secondary[index:index + 2], 16) for index in (0, 2, 4))
        count = int(self.get_parameter('led_count').value)
        enabled = bool(self.get_parameter('enabled').value)
        message = LedStripState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'led_strip'
        message.connected = True
        message.enabled = enabled
        message.led_count = count
        message.lit_count = count if enabled else 0
        message.brightness = float(self.get_parameter('brightness').value)
        message.effect = str(self.get_parameter('effect').value)
        message.effect_speed_hz = float(self.get_parameter('effect_speed_hz').value)
        message.pixel_order = 'GRB'
        message.backend = 'gazebo-mock'
        message.status_message = 'Simulated LED strip is ready'
        message.transport = 'simulation'
        message.red, message.green, message.blue = primary_rgb
        message.secondary_red, message.secondary_green, message.secondary_blue = secondary_rgb
        packed = (primary_rgb[0] << 16) | (primary_rgb[1] << 8) | primary_rgb[2]
        message.preview_colors = [packed if enabled else 0] * count
        self.compat_publisher.publish(message)
        native = LEDStateArray()
        native.leds = list(self.manual_leds)
        self.native_publisher.publish(native)


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node = MockIo()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
