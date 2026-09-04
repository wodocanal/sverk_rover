from __future__ import annotations

import math
from typing import Optional

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

from rover_interfaces.msg import WheelEncoders


WHEEL_JOINTS = (
    'front_left_wheel_joint',
    'front_right_wheel_joint',
    'rear_left_wheel_joint',
    'rear_right_wheel_joint',
)


class EncoderAdapter(Node):
    def __init__(self) -> None:
        super().__init__('sim_encoder_adapter')
        self.declare_parameter('joint_states_topic', '/joint_states')
        self.declare_parameter('encoder_topic', '/wheel/encoders')
        self.declare_parameter('wheel_radius_m', 0.03)
        self.declare_parameter('encoder_lines', 11.0)
        self.declare_parameter('reduction_ratio', 45.0)
        self.declare_parameter('quadrature_factor', 4.0)
        self.radius = float(self.get_parameter('wheel_radius_m').value)
        self.counts_per_revolution = (
            float(self.get_parameter('encoder_lines').value)
            * float(self.get_parameter('reduction_ratio').value)
            * float(self.get_parameter('quadrature_factor').value)
        )
        self.sequence = 0
        self.publisher = self.create_publisher(
            WheelEncoders,
            str(self.get_parameter('encoder_topic').value),
            20,
        )
        self.subscription = self.create_subscription(
            JointState,
            str(self.get_parameter('joint_states_topic').value),
            self._on_joint_state,
            20,
        )

    def _on_joint_state(self, message: JointState) -> None:
        indices = {name: index for index, name in enumerate(message.name)}
        if any(name not in indices for name in WHEEL_JOINTS):
            return

        positions = []
        velocities = []
        for name in WHEEL_JOINTS:
            index = indices[name]
            if index >= len(message.position):
                return
            positions.append(float(message.position[index]))
            velocity = (
                float(message.velocity[index])
                if index < len(message.velocity)
                else 0.0
            )
            velocities.append(velocity)

        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        output = WheelEncoders()
        output.header.stamp = message.header.stamp
        output.header.frame_id = 'base_link'
        output.total_counts = [
            int(round(position / (2.0 * math.pi) * self.counts_per_revolution))
            for position in positions
        ]
        output.measured_mps = [velocity * self.radius for velocity in velocities]
        output.sequence = self.sequence
        output.valid = True
        self.publisher.publish(output)


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node = EncoderAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
