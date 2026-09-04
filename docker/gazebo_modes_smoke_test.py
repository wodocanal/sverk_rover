#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Odometry, Path
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rcl_interfaces.srv import SetParameters
from sensor_msgs.msg import Image

from ros_smoke_test import ManagedLaunch, SmokeFailure, web_identity


class ModeProbe(Node):
    def __init__(self) -> None:
        super().__init__(
            'gazebo_modes_probe',
            parameter_overrides=[Parameter('use_sim_time', value=True)],
        )
        self.latest = {}
        map_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions_to_keep = []
        for name, topic, message_type, qos in (
            ('map', '/map', OccupancyGrid, map_qos),
            ('odom', '/odom', Odometry, 10),
            ('pose', '/amcl_pose', PoseWithCovarianceStamped, 10),
            ('plan', '/plan', Path, 10),
            ('raw_image', '/image_raw', Image, qos_profile_sensor_data),
            ('image', '/image_processed', Image, qos_profile_sensor_data),
        ):
            self.subscriptions_to_keep.append(self.create_subscription(
                message_type, topic,
                lambda message, key=name: self.latest.__setitem__(key, message),
                qos,
            ))
        self.navigator = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.vision_parameters = self.create_client(
            SetParameters, '/camera_detector_node/set_parameters',
        )

    def spin_and_check(self, predicate) -> bool:
        rclpy.spin_once(self, timeout_sec=0.1)
        return bool(predicate())

    def has_map(self) -> bool:
        message = self.latest.get('map')
        return (
            message is not None and message.info.width > 0
            and message.info.height > 0 and any(cell == 0 for cell in message.data)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description='Test SLAM or a full Nav2 goal in Gazebo.')
    parser.add_argument('mode', choices=['mapping', 'navigation'])
    parser.add_argument('--goal-x', type=float, default=0.5)
    parser.add_argument('--goal-y', type=float, default=0.0)
    args = parser.parse_args()
    rclpy.init(args=[])
    probe = ModeProbe()
    try:
        with ManagedLaunch([
            'ros2', 'launch', 'rover_bringup', 'simulation.launch.py',
            'world:=field', f'mode:={args.mode}', 'gui:=false',
            'headless_rendering:=true', 'ui_profile:=web', 'web_port:=18765',
            'integrations_profile:=none', 'use_vision:=true',
        ]) as launch:
            launch.wait_until(
                lambda: probe.spin_and_check(lambda: (
                    probe.has_map() and 'odom' in probe.latest
                    and 'raw_image' in probe.latest
                )),
                f'{args.mode}: map, odometry and camera image',
                timeout=120.0,
            )
            launch.wait_until(
                lambda: bool(web_identity(18765)),
                'web identity API', timeout=20.0,
            )
            manager = (
                'lifecycle_manager_slam' if args.mode == 'mapping'
                else 'lifecycle_manager_navigation'
            )
            launch.wait_until(
                lambda: any(
                    manager in line and 'Managed nodes are active' in line
                    for line in launch.read_output().splitlines()
                ),
                f'{manager}: lifecycle startup and bonds', timeout=90.0,
            )
            launch.wait_until(
                probe.vision_parameters.service_is_ready,
                'vision parameter service', timeout=15.0,
            )
            request = SetParameters.Request()
            request.parameters = [Parameter('enabled', value=True).to_parameter_msg()]
            vision_future = probe.vision_parameters.call_async(request)
            launch.wait_until(
                lambda: probe.spin_and_check(vision_future.done),
                'enable vision', timeout=30.0,
            )
            for result in vision_future.result().results:
                if not result.successful:
                    raise SmokeFailure(f'Vision activation failed: {result.reason}')
            launch.wait_until(
                lambda: probe.spin_and_check(lambda: 'image' in probe.latest),
                'processed image from vision', timeout=45.0,
            )
            if args.mode == 'navigation':
                launch.wait_until(
                    lambda: probe.spin_and_check(lambda: (
                        'pose' in probe.latest
                        and 'Published simulated initial pose #3' in launch.read_output()
                        and probe.navigator.server_is_ready()
                    )),
                    'AMCL initial pose and NavigateToPose action', timeout=90.0,
                )
                start = probe.latest['odom'].pose.pose.position
                start_xy = (start.x, start.y)
                goal = NavigateToPose.Goal()
                goal.pose.header.frame_id = 'map'
                goal.pose.header.stamp = probe.get_clock().now().to_msg()
                goal.pose.pose.position.x = args.goal_x
                goal.pose.pose.position.y = args.goal_y
                goal.pose.pose.orientation.w = 1.0
                pending = probe.navigator.send_goal_async(goal)
                launch.wait_until(
                    lambda: probe.spin_and_check(pending.done),
                    'navigation goal acceptance', timeout=15.0,
                )
                handle = pending.result()
                if not handle.accepted:
                    raise SmokeFailure('NavigateToPose rejected the goal')
                result_future = handle.get_result_async()
                launch.wait_until(
                    lambda: probe.spin_and_check(result_future.done),
                    'navigation goal result', timeout=120.0,
                )
                result = result_future.result()
                if result.status != GoalStatus.STATUS_SUCCEEDED:
                    raise SmokeFailure(
                        f'Navigation failed: status={result.status}, result={result.result}'
                    )
                position = probe.latest['odom'].pose.pose.position
                distance = math.hypot(position.x - start_xy[0], position.y - start_xy[1])
                if distance < 0.2:
                    raise SmokeFailure(f'Goal succeeded without enough motion: {distance:.3f} m')
                if 'plan' not in probe.latest or len(probe.latest['plan'].poses) < 2:
                    raise SmokeFailure('No non-empty Nav2 path was published on /plan')
                print(
                    f'[sim-modes] SUCCEEDED: goal=({args.goal_x}, {args.goal_y}), '
                    f'odom=({position.x:.3f}, {position.y:.3f}), moved={distance:.3f} m',
                    flush=True,
                )
            output = launch.read_output()
            if '[FATAL]' in output or 'Failed to bring up' in output:
                raise SmokeFailure('A fatal startup error was found in the launch log')
            grid = probe.latest['map']
            print(
                f'[sim-modes] PASS: {args.mode}, map={grid.info.width}x{grid.info.height}, '
                'vision and web API', flush=True,
            )
    finally:
        probe.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    try:
        main()
    except SmokeFailure as exc:
        print(f'[sim-modes] FAIL: {exc}', flush=True)
        raise SystemExit(1)
