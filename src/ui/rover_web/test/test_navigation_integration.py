"""Opt-in HTTP/SLAM/Nav2 integration test, isolated from physical hardware.

Run in a sourced ROS workspace with ROVER_WEB_NAV_INTEGRATION=1.
"""

import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster

from rover_web.web_gateway_node import RoverWebGateway


@pytest.mark.skipif(os.getenv('ROVER_WEB_NAV_INTEGRATION') != '1', reason='opt-in real SLAM/Nav2 test')
def test_mapping_save_navigation_and_stop(tmp_path):
    rclpy.init(args=['--ros-args', '-p', 'port:=0', '-p', f'maps_root:={tmp_path}/maps/current',
                     '-p', f'hackathon_files_root:={tmp_path}/files',
                     '-p', f'plans_directory:={tmp_path}/plans'])
    gateway = RoverWebGateway()
    sensor = Node('test_navigation_sensors')
    executor = SingleThreadedExecutor()
    executor.add_node(gateway)
    executor.add_node(sensor)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    url = f'http://127.0.0.1:{gateway._http_server.server_port}'

    def api(path, payload=None):
        request = Request(url + path, data=None if payload is None else json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=10) as response:
                return json.load(response)
        except HTTPError as exc:
            print(path, exc.read().decode())
            raise

    def wait_for(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = api('/api/navigation/status')
            if predicate(status):
                return status
            time.sleep(0.2)
        pytest.fail(json.dumps(status, indent=2))

    try:
        assert api('/api/status')['navigation']['running'] is False
        with pytest.raises(HTTPError):
            api('/api/mapping/start', {})
        scan_pub = sensor.create_publisher(LaserScan, '/scan_filtered', 10)
        odom_pub = sensor.create_publisher(Odometry, '/odom', 10)
        dynamic = TransformBroadcaster(sensor)
        static = StaticTransformBroadcaster(sensor)
        transform = TransformStamped()
        transform.header.frame_id = 'base_link'
        transform.child_frame_id = 'laser'
        transform.transform.rotation.w = 1.0
        static.sendTransform(transform)

        def tick():
            stamp = sensor.get_clock().now().to_msg()
            tf = TransformStamped()
            tf.header.stamp = stamp
            tf.header.frame_id = 'odom'
            tf.child_frame_id = 'base_link'
            tf.transform.rotation.w = 1.0
            dynamic.sendTransform(tf)
            odom = Odometry()
            odom.header.stamp = stamp
            odom.header.frame_id = 'odom'
            odom.child_frame_id = 'base_link'
            odom.pose.pose.orientation.w = 1.0
            odom_pub.publish(odom)
            scan = LaserScan()
            scan.header.stamp = stamp
            scan.header.frame_id = 'laser'
            scan.angle_min = -math.pi
            scan.angle_increment = math.tau / 360
            scan.angle_max = scan.angle_min + 359 * scan.angle_increment
            scan.range_min = 0.05
            scan.range_max = 10.0
            scan.ranges = [2.0 / max(abs(math.cos(a)), abs(math.sin(a)))
                           for a in [scan.angle_min + i * scan.angle_increment for i in range(360)]]
            scan_pub.publish(scan)

        sensor.create_timer(0.1, tick)
        wait_for(lambda s: s['prerequisites']['ready'])
        api('/api/mapping/start', {})
        with pytest.raises(HTTPError):
            api('/api/mapping/start', {})
        wait_for(lambda s: s['live_map'] is not None)
        with urlopen(url + '/api/mapping/image') as image:
            assert image.read().startswith(b'\x89PNG')
        api('/api/mapping/save', {'label': 'test_room'})
        wait_for(lambda s: s['map_save']['state'] == 'saved', timeout=45)
        assert (tmp_path / 'maps/current/map.yaml').is_file()
        assert (tmp_path / 'maps/current/map.posegraph').is_file()
        api('/api/navigation/stop', {})
        wait_for(lambda s: not s['running'] and not s['external']['slam'])
        with pytest.raises(HTTPError):
            api('/api/navigation/start', {'map': 'map.yaml'})
        api('/api/navigation/start', {'map': 'map.yaml',
                                     'initial_pose': {'x': 0, 'y': 0, 'yaw': 0},
                                     'goal': {'x': 0, 'y': 0, 'yaw': 0}})
        status = wait_for(lambda s: s['goal_state'] == 'succeeded', timeout=75)
        assert status['phase'] == 'running'
        assert status['map_pose'] is not None
        api('/api/navigation/goal', {'goal': {'x': 1, 'y': 0, 'yaw': 0}})
        wait_for(lambda s: s['goal_state'] == 'active' and len(s['planned_path']) > 1)
        api('/api/navigation/cancel', {})
        wait_for(lambda s: s['goal_state'] == 'canceled')
        api('/api/stop', {})
        wait_for(lambda s: not s['running'])
    finally:
        gateway.stop_navigation_runtime()
        process = gateway._navigation_process
        if process is not None:
            process.wait(timeout=15)
        executor.shutdown(timeout_sec=5)
        worker.join(timeout=5)
        gateway.destroy_node()
        sensor.destroy_node()
        rclpy.shutdown()
