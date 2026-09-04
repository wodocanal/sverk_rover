from __future__ import annotations

from typing import Optional

from geometry_msgs.msg import Twist, TwistStamped
import rclpy
from rclpy.node import Node


class TwistAdapter(Node):
    def __init__(self) -> None:
        super().__init__('sim_twist_adapter')
        self.declare_parameter('input_topic', '/cmd_vel')
        self.declare_parameter(
            'output_topic', '/mecanum_drive_controller/reference'
        )
        output_topic = str(self.get_parameter('output_topic').value)
        input_topic = str(self.get_parameter('input_topic').value)
        self.publisher = self.create_publisher(TwistStamped, output_topic, 10)
        self.subscription = self.create_subscription(
            Twist, input_topic, self._on_twist, 10
        )
        self.get_logger().info(
            f'Converting {input_topic} Twist commands to {output_topic} TwistStamped'
        )

    def _on_twist(self, message: Twist) -> None:
        stamped = TwistStamped()
        stamped.header.stamp = self.get_clock().now().to_msg()
        stamped.header.frame_id = 'base_link'
        stamped.twist = message
        self.publisher.publish(stamped)


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node = TwistAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
