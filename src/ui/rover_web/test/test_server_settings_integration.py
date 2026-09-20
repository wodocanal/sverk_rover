"""Exercise HTTP -> private file -> ROS reload service -> actual Paho handshake."""
import json
import socketserver
import threading
import time
from urllib.request import Request, urlopen

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from fleet_text_bridge_ros2.bridge_node import FleetTextBridge
from rover_web.web_gateway_node import RoverWebGateway


class Broker(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class MQTTHandler(socketserver.BaseRequestHandler):
    def handle(self):
        def read(size):
            data = b''
            while len(data) < size:
                part = self.request.recv(size - len(data))
                if not part:
                    raise EOFError()
                data += part
            return data
        try:
            while True:
                header = read(1)[0]
                size, multiplier = 0, 1
                while True:
                    byte = read(1)[0]
                    size += (byte & 127) * multiplier
                    if byte < 128:
                        break
                    multiplier *= 128
                body = read(size)
                kind = header >> 4
                if kind == 1:
                    self.server.client_socket = self.request
                    self.server.connects.append(body)
                    self.request.sendall(b'\x20\x02\x00\x00')
                elif kind == 8:
                    self.request.sendall(b'\x90\x03' + body[:2] + b'\x01')
                elif kind == 3 and ((header >> 1) & 3) == 1:
                    offset = 2 + int.from_bytes(body[:2], 'big')
                    self.server.messages.append(body[offset + 2:])
                    self.request.sendall(b'\x40\x02' + body[offset:offset + 2])
                elif kind == 12:
                    self.request.sendall(b'\xd0\x00')
                elif kind == 14:
                    return
        except (OSError, EOFError):
            pass


def test_web_save_reconnect_busy_guard_and_restart(tmp_path):
    brokers = [Broker(('127.0.0.1', 0), MQTTHandler) for _ in range(2)]
    for broker in brokers:
        broker.connects, broker.messages = [], []
        threading.Thread(target=broker.serve_forever, daemon=True).start()
    settings_file = tmp_path / 'mqtt.json'
    rclpy.init(args=['--ros-args', '-p', 'port:=0', '-p', 'mqtt_host:=127.0.0.1',
        '-p', f'mqtt_port:={brokers[0].server_address[1]}', '-p', 'mqtt_username:=""',
        '-p', 'robot_id:=connection-test', '-p', f'connection_settings_file:={settings_file}',
        '-p', f'fleet_settings_file:={settings_file}', '-p', f'hackathon_files_root:={tmp_path}/files',
        '-p', f'plans_directory:={tmp_path}/plans'])
    executor = SingleThreadedExecutor()
    bridge = gateway = worker = None
    try:
        bridge, gateway = FleetTextBridge(), RoverWebGateway()
        executor.add_node(bridge)
        executor.add_node(gateway)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{gateway._http_server.server_port}/api/server/settings'

        def api(payload=None):
            request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                              headers={'Content-Type':'application/json'})
            with urlopen(request, timeout=12) as response:
                return json.load(response)

        def wait_for(predicate):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(.1)
            raise AssertionError('Timed out waiting for MQTT state')

        wait_for(lambda: api()['connection']['ready'])
        data = api()
        assert data['can_reconnect']
        assert data['settings']['mqtt_port'] == brokers[0].server_address[1]
        values = {**data['settings'], 'mqtt_port':brokers[1].server_address[1],
                  'mqtt_username':'test-user', 'mqtt_password':'test-only-secret'}
        result = api({'settings':values})
        assert not result['reconnect']['started']
        assert bridge._mqtt_settings['mqtt_port'] == brokers[0].server_address[1]
        assert 'test-only-secret' not in json.dumps(result)
        values['mqtt_password'] = ''
        result = api({'settings':values, 'reconnect':True})
        assert result['reconnect']['started']
        wait_for(lambda: api()['connection'].get('port') == brokers[1].server_address[1]
                        and api()['connection']['ready'])
        assert b'test-only-secret' in brokers[1].connects[-1]
        assert any(json.loads(msg).get('online') is False for msg in brokers[0].messages)
        assert bridge.robot_id == 'connection-test'
        bridge._active_command = {'message_id':'test-active'}
        bridge._active_since = time.monotonic()
        count = len(brokers[1].connects)
        result = api({'settings':values,'reconnect':True})
        assert not result['reconnect']['started']
        assert 'processing commands' in result['reconnect']['message']
        assert len(brokers[1].connects) == count
        bridge._active_command = None
        executor.remove_node(bridge)
        bridge.destroy_node()
        bridge = FleetTextBridge()
        executor.add_node(bridge)
        wait_for(lambda: len(brokers[1].connects) > count and bridge._connection['state'] == 'connected')
        assert bridge._mqtt_settings['mqtt_password'] == 'test-only-secret'
        assert bridge._mqtt_settings['mqtt_port'] == brokers[1].server_address[1]
    finally:
        executor.shutdown(timeout_sec=3)
        if worker:
            worker.join(timeout=3)
        if bridge:
            bridge.destroy_node()
        if gateway:
            gateway.destroy_node()
        rclpy.shutdown()
        for broker in brokers:
            broker.shutdown()
            broker.server_close()


def test_mqtt_received_commands_visible_while_queued_and_correlated_with_answers(tmp_path):
    broker = Broker(('127.0.0.1', 0), MQTTHandler)
    broker.connects, broker.messages = [], []
    threading.Thread(target=broker.serve_forever, daemon=True).start()
    rclpy.init(args=['--ros-args', '-p', 'port:=0', '-p', 'mqtt_host:=127.0.0.1',
        '-p', f'mqtt_port:={broker.server_address[1]}', '-p', 'mqtt_username:=""',
        '-p', 'robot_id:=connection-test', '-p', f'connection_settings_file:={tmp_path}/mqtt.json',
        '-p', f'hackathon_files_root:={tmp_path}/files', '-p', f'plans_directory:={tmp_path}/plans'])
    executor = SingleThreadedExecutor()
    bridge = gateway = agent = worker = None
    try:
        gateway, bridge, agent = RoverWebGateway(), FleetTextBridge(), Node('test_receiving_agent')
        commands = []
        agent.create_subscription(String, '/agent/text_command', lambda msg: commands.append(json.loads(msg.data)), 10)
        answers = agent.create_publisher(String, '/agent/answer', 10)
        for node in (gateway, bridge, agent):
            executor.add_node(node)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{gateway._http_server.server_port}/api/agent'

        def get():
            with urlopen(url, timeout=5) as response:
                return json.load(response)

        def wait_for(predicate):
            deadline = time.monotonic()+8
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(.1)
            raise AssertionError('Timed out waiting for server message')

        def send(command):
            topic = bridge.command_mqtt_topic.encode()
            body = len(topic).to_bytes(2, 'big') + topic + json.dumps(command, ensure_ascii=False).encode()
            size, encoded = len(body), bytearray()
            while True:
                byte, size = size % 128, size // 128
                encoded.append(byte | (128 if size else 0))
                if not size:
                    break
            broker.client_socket.sendall(b'\x30' + bytes(encoded) + body)

        wait_for(lambda: get()['server_connection']['ready'] and get()['input_subscribers'] == 1)
        first = {'message_id':'1dfdcaf6-ff60-4bb1-b874-d399fb4a5ae7',
                 'robot_id':'connection-test', 'text':'Сообщи статус <script>test</script>'}
        second = {**first,'message_id':'1dfdcaf6-ff60-4bb1-b874-d399fb4a5ae8','text':'Второе сообщение'}
        send(first)
        wait_for(lambda: len(commands) == 1 and len(get()['messages']) == 1)
        send(second)
        send(second)
        send({**second,'robot_id':'different-robot','message_id':'wrong-robot'})
        wait_for(lambda: len(get()['messages']) == 2)
        messages = get()['messages']
        assert messages[0]['source'] == messages[1]['source'] == 'server'
        assert messages[0]['text'] == first['text']
        assert messages[1]['status'] == 'queued'
        assert len(commands) == 1
        answers.publish(String(data=json.dumps({**first,'status':'completed','text':'Первый ответ'})))
        wait_for(lambda: len(commands) == 2 and get()['messages'][0]['answer'] == 'Первый ответ')
        answers.publish(String(data=json.dumps({**second,'status':'completed','text':'Второй ответ'})))
        wait_for(lambda: get()['messages'][1]['answer'] == 'Второй ответ')
        assert len(get()['messages']) == 2
        assert get()['input_subscribers'] == 1  # The web observer must not look like an agent.
    finally:
        executor.shutdown(timeout_sec=3)
        if worker:
            worker.join(timeout=3)
        for node in (bridge, gateway, agent):
            if node:
                node.destroy_node()
        rclpy.shutdown()
        broker.shutdown()
        broker.server_close()
