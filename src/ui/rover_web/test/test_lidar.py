"""ROS-level regression tests without cameras, USB devices or a running rover."""

import math
import threading
import time
import unittest

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

from rover_web.web_gateway_node import LASER_SCAN_TYPE, RoverWebGateway


def scan(ranges):
    message = LaserScan()
    message.header.frame_id = 'lidar_link'
    message.range_min = 0.1
    message.range_max = 12.0
    message.angle_min = 0.0
    message.angle_increment = 0.01
    message.ranges = ranges
    return message


class WatchHarness(Node):
    _ensure_topic_watch = RoverWebGateway._ensure_topic_watch
    _message_summary = RoverWebGateway._message_summary

    def __init__(self, context):
        super().__init__('lidar_web_watch_test', context=context)
        self._lock = threading.RLock()
        self._topic_watches = {}


class LidarTests(unittest.TestCase):
    def test_best_effort_and_reliable_publishers_both_reach_web_watch(self):
        context = Context()
        rclpy.init(context=context)
        node = WatchHarness(context)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        try:
            publishers = []
            watches = []
            for suffix, qos in [('raw', 10), ('filtered', qos_profile_sensor_data)]:
                topic = f'/rover_web_test/{suffix}'
                publishers.append(node.create_publisher(LaserScan, topic, qos))
                watch = node._ensure_topic_watch(topic, LASER_SCAN_TYPE)
                self.assertEqual(watch.subscription.qos_profile.reliability,
                                 ReliabilityPolicy.BEST_EFFORT)
                watches.append(watch)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not all(w.message_count for w in watches):
                for publisher in publishers:
                    publisher.publish(scan([1.0, math.inf, 2.0]))
                executor.spin_once(timeout_sec=0.05)
            for watch in watches:
                self.assertGreater(watch.message_count, 0)
                self.assertIsNone(watch.last_error)
                self.assertIsNotNone(watch.raw_message)
                payload = RoverWebGateway._scan_points_payload(node, watch.raw_message)
                self.assertEqual(payload['valid_points'], 2)
        finally:
            executor.shutdown()
            node.destroy_node()
            context.shutdown()

    def test_sparse_filtered_scan_is_not_lost_by_downsampling(self):
        ranges = [math.inf if index % 2 == 0 else 1.0 for index in range(1440)]
        payload = RoverWebGateway._scan_points_payload(None, scan(ranges))
        self.assertEqual(payload['total_ranges'], 1440)
        self.assertEqual(payload['valid_points'], 720)
        self.assertEqual(len(payload['points']), 720)

    def test_valid_count_is_not_downsampled(self):
        payload = RoverWebGateway._scan_points_payload(None, scan([1.0] * 2000))
        self.assertEqual(payload['valid_points'], 2000)
        self.assertLessEqual(len(payload['points']), 720)

    def test_nonfinite_and_out_of_range_returns_are_skipped(self):
        payload = RoverWebGateway._scan_points_payload(
            None, scan([math.nan, math.inf, -math.inf, 0.0, 13.0, 1.0]),
        )
        self.assertEqual(payload['valid_points'], 1)
        self.assertTrue(all(math.isfinite(v) for point in payload['points'] for v in point))

    def test_empty_scan(self):
        payload = RoverWebGateway._scan_points_payload(None, scan([]))
        self.assertEqual(payload['points'], [])
        self.assertEqual(payload['valid_points'], 0)


if __name__ == '__main__':
    unittest.main()
