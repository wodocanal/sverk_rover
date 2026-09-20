"""Real Paho/ROS bridge against a minimal local MQTT handshake test double."""
import json
import socket
import threading
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from fleet_text_bridge_ros2.bridge_node import FleetTextBridge


def test_mqtt_handshake_and_disconnect_reach_ros():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(8)
    port = listener.getsockname()[1]
    connections = []

    def broker():
        def read(stream, count):
            data = b''
            while len(data) < count:
                part = stream.recv(count-len(data))
                if not part: raise EOFError()
                data += part
            return data
        try:
            stream, _ = listener.accept()
            connections.append(stream)
            with stream:
                stream.settimeout(8)
                while True:
                    header = read(stream, 1)[0]
                    size, multiplier = 0, 1
                    while True:
                        byte = read(stream, 1)[0]
                        size += (byte & 127)*multiplier
                        if byte < 128: break
                        multiplier *= 128
                    body = read(stream, size)
                    kind = header >> 4
                    if kind == 1: stream.sendall(b'\x20\x02\x00\x00')
                    elif kind == 8: stream.sendall(b'\x90\x03'+body[:2]+b'\x01')
                    elif kind == 3 and (header >> 1) & 3 == 1:
                        offset = 2 + int.from_bytes(body[:2], 'big')
                        stream.sendall(b'\x40\x02'+body[offset:offset+2])
                    elif kind == 12: stream.sendall(b'\xd0\x00')
                    elif kind == 14: break
        except (OSError, EOFError):
            pass

    broker_thread = threading.Thread(target=broker, daemon=True)
    broker_thread.start()
    rclpy.init(args=['--ros-args', '-p', 'mqtt_host:=127.0.0.1', '-p', f'mqtt_port:={port}',
                    '-p', 'mqtt_username:=""', '-p', 'robot_id:=connection-test',
                    '-p', 'connection_topic:=/test/fleet_connection'])
    bridge = observer = worker = None
    executor = SingleThreadedExecutor()
    states = []
    try:
        bridge = FleetTextBridge()
        observer = Node('connection_test_observer')
        observer.create_subscription(String, '/test/fleet_connection',
            lambda msg: states.append(json.loads(msg.data)), 10)
        executor.add_node(bridge)
        executor.add_node(observer)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        deadline = time.monotonic()+8
        while time.monotonic() < deadline and not any(s['state']=='connected' for s in states):
            time.sleep(.1)
        assert any(s['connected'] and s['subscribed'] and s['availability_confirmed'] for s in states)
        listener.close()
        connections[0].shutdown(socket.SHUT_RDWR)
        deadline = time.monotonic()+5
        while time.monotonic() < deadline and states[-1]['connected']:
            time.sleep(.1)
        assert not states[-1]['connected']
        assert states[-1]['state'] == 'disconnected'
    finally:
        listener.close()
        executor.shutdown(timeout_sec=3)
        if worker: worker.join(timeout=3)
        if bridge: bridge.destroy_node()
        if observer: observer.destroy_node()
        broker_thread.join(timeout=2)
        rclpy.shutdown()
