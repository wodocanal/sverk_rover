from __future__ import annotations

import math
from typing import Optional

from geometry_msgs.msg import PoseWithCovarianceStamped
import rclpy
from rclpy.node import Node


class InitialPosePublisher(Node):
    def __init__(self) -> None:
        super().__init__('sim_initial_pose_publisher')
        self.declare_parameter('topic', '/initialpose')
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('x', 0.0)
        self.declare_parameter('y', 0.0)
        self.declare_parameter('yaw', 0.0)
        self.declare_parameter('delay_sec', 11.0)
        self.publisher = self.create_publisher(
            PoseWithCovarianceStamped,
            str(self.get_parameter('topic').value),
            10,
        )
        self.started_at = self.get_clock().now()
        self.publish_count = 0
        self.done = False
        self.timer = self.create_timer(0.5, self._tick)

    def _tick(self) -> None:
        delay = float(self.get_parameter('delay_sec').value)
        elapsed = (self.get_clock().now() - self.started_at).nanoseconds / 1e9
        if elapsed < delay or self.publisher.get_subscription_count() == 0:
            return

        yaw = float(self.get_parameter('yaw').value)
        message = PoseWithCovarianceStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = str(self.get_parameter('frame_id').value)
        message.pose.pose.position.x = float(self.get_parameter('x').value)
        message.pose.pose.position.y = float(self.get_parameter('y').value)
        message.pose.pose.orientation.z = math.sin(yaw / 2.0)
        message.pose.pose.orientation.w = math.cos(yaw / 2.0)
        message.pose.covariance[0] = 0.05 ** 2
        message.pose.covariance[7] = 0.05 ** 2
        message.pose.covariance[35] = 0.10 ** 2
        self.publisher.publish(message)
        self.publish_count += 1
        self.get_logger().info(
            f'Published simulated initial pose #{self.publish_count}: '
            f'x={message.pose.pose.position.x:.3f}, '
            f'y={message.pose.pose.position.y:.3f}, yaw={yaw:.3f}'
        )
        if self.publish_count >= 3:
            self.done = True


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node = InitialPosePublisher()
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
