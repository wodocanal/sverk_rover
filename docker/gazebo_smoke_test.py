#!/usr/bin/env python3
from __future__ import annotations

import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from geometry_msgs.msg import Twist
from controller_manager_msgs.srv import ListControllers
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, Imu, JointState, LaserScan

from rover_interfaces.msg import WheelEncoders


WORKSPACE = Path(os.environ.get('ROVER_WS', '/workspace')).resolve()
STARTUP_TIMEOUT_SEC = 90.0


class SimulationFailure(RuntimeError):
    pass


def yaw_from_odom(message: Odometry) -> float:
    q = message.pose.pose.orientation
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


def angle_delta(current: float, previous: float) -> float:
    return math.atan2(math.sin(current - previous), math.cos(current - previous))


class Probe(Node):
    def __init__(self) -> None:
        super().__init__('gazebo_smoke_probe')
        self.latest: dict[str, object] = {}
        # Keep explicit references so rclpy does not garbage-collect subscriptions.
        self.probe_subscriptions = [
            self.create_subscription(
                LaserScan, '/scan_filtered',
                lambda msg: self.latest.__setitem__('scan', msg),
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                Imu, '/imu/data',
                lambda msg: self.latest.__setitem__('imu', msg),
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                Image, '/image_raw',
                lambda msg: self.latest.__setitem__('image', msg),
                qos_profile_sensor_data,
            ),
            self.create_subscription(
                JointState, '/joint_states',
                lambda msg: self.latest.__setitem__('joints', msg),
                20,
            ),
            self.create_subscription(
                WheelEncoders, '/wheel/encoders',
                lambda msg: self.latest.__setitem__('encoders', msg),
                20,
            ),
            self.create_subscription(
                Odometry, '/odom',
                lambda msg: self.latest.__setitem__('odom', msg),
                20,
            ),
        ]
        self.command_publisher = self.create_publisher(
            Twist, '/cmd_vel_teleop', 10
        )
        self.controller_client = self.create_client(
            ListControllers, '/controller_manager/list_controllers'
        )

    def wait_for_drive_controller(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if not self.controller_client.wait_for_service(timeout_sec=0.5):
                continue
            future = self.controller_client.call_async(ListControllers.Request())
            rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)
            if not future.done() or future.exception() is not None:
                continue
            for controller in future.result().controller:
                if (
                    controller.name == 'mecanum_drive_controller'
                    and controller.state == 'active'
                ):
                    print(
                        '[sim-smoke] ready: mecanum_drive_controller is active',
                        flush=True,
                    )
                    return
            time.sleep(0.2)
        raise SimulationFailure(
            'Timed out waiting for active mecanum_drive_controller'
        )

    def wait_for_data(self) -> None:
        required = {'scan', 'imu', 'image', 'joints', 'encoders', 'odom'}
        deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            missing = required.difference(self.latest)
            if not missing:
                print('[sim-smoke] ready: ' + ', '.join(sorted(required)), flush=True)
                return
        raise SimulationFailure(
            'Timed out waiting for simulated data: '
            + ', '.join(sorted(required.difference(self.latest)))
        )

    def command(self, *, x: float = 0.0, y: float = 0.0, yaw: float = 0.0,
                duration: float = 2.0) -> None:
        message = Twist()
        message.linear.x = x
        message.linear.y = y
        message.angular.z = yaw
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            self.command_publisher.publish(message)
            rclpy.spin_once(self, timeout_sec=0.05)
            time.sleep(0.05)
        stop = Twist()
        for _ in range(10):
            self.command_publisher.publish(stop)
            rclpy.spin_once(self, timeout_sec=0.05)

    def pose(self) -> tuple[float, float, float]:
        message = self.latest.get('odom')
        if not isinstance(message, Odometry):
            raise SimulationFailure('No odometry sample is available')
        return (
            float(message.pose.pose.position.x),
            float(message.pose.pose.position.y),
            yaw_from_odom(message),
        )


def output_tail(stream, lines: int = 180) -> str:
    stream.flush()
    stream.seek(0)
    return '\n'.join(stream.read().splitlines()[-lines:])


def main() -> int:
    if not (WORKSPACE / 'install' / 'setup.bash').is_file():
        raise SimulationFailure('Workspace is not built; run make ros-build first')

    command = [
        'ros2', 'launch', 'rover_bringup', 'simulation.launch.py',
        'world:=empty', 'gui:=false', 'headless_rendering:=true',
        'mode:=idle', 'ui_profile:=none', 'integrations_profile:=none',
        'use_vision:=false',
    ]
    print(f"[sim-smoke] $ {' '.join(command)}", flush=True)
    output = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
    process = subprocess.Popen(
        command,
        stdout=output,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    probe = None
    try:
        time.sleep(2.0)
        if process.poll() is not None:
            raise SimulationFailure(
                f'Simulation exited with code {process.returncode}:\n{output_tail(output)}'
            )
        rclpy.init()
        probe = Probe()
        probe.wait_for_data()
        probe.wait_for_drive_controller()

        start = probe.pose()
        probe.command(x=0.14, duration=2.5)
        forward = probe.pose()
        forward_delta = forward[0] - start[0]
        if forward_delta < 0.08:
            raise SimulationFailure(
                f'Forward command moved only {forward_delta:.3f} m; poses={start}->{forward}'
            )

        probe.command(y=0.12, duration=2.5)
        lateral = probe.pose()
        lateral_delta = lateral[1] - forward[1]
        if lateral_delta < 0.05:
            raise SimulationFailure(
                f'Lateral command moved only {lateral_delta:.3f} m; poses={forward}->{lateral}'
            )

        probe.command(yaw=0.6, duration=2.0)
        rotated = probe.pose()
        yaw_delta = angle_delta(rotated[2], lateral[2])
        if yaw_delta < 0.20:
            raise SimulationFailure(
                f'Rotation command changed yaw only {yaw_delta:.3f} rad; '
                f'poses={lateral}->{rotated}'
            )

        image = probe.latest['image']
        scan = probe.latest['scan']
        print(
            '[sim-smoke] motion: '
            f'forward={forward_delta:.3f} m, lateral={lateral_delta:.3f} m, '
            f'yaw={yaw_delta:.3f} rad',
            flush=True,
        )
        print(
            f'[sim-smoke] sensors: image={image.width}x{image.height}, '
            f'lidar_samples={len(scan.ranges)}',
            flush=True,
        )
        print('[sim-smoke] PASS: Gazebo drive, odometry and sensors', flush=True)
        return 0
    except Exception:
        print('\n[sim-smoke] launch output tail:\n' + output_tail(output), flush=True)
        raise
    finally:
        if probe is not None:
            probe.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=15.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=8.0)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3.0)
        output.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (SimulationFailure, subprocess.SubprocessError) as exc:
        print(f'\n[sim-smoke] FAIL: {exc}', flush=True)
        raise SystemExit(1)
