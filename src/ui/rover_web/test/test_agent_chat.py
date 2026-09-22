import json
import threading
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from rover_web.agent_chat import AgentChatMixin
from rover_web.web_gateway_node import RoverWebGateway


def bare_chat():
    chat = AgentChatMixin()
    chat.declare_parameter = Mock()
    chat.get_parameter = lambda name: type('P', (), {'value': name})()
    chat.create_publisher = Mock(return_value=Mock())
    chat.create_subscription = Mock()
    chat.count_subscribers = Mock(return_value=1)
    chat.count_publishers = Mock(return_value=1)
    chat._motor_calibration_active = False
    chat.init_agent_chat()
    return chat


def test_send_validation_duplicate_and_interlock():
    chat = bare_chat()
    request = {'text': 'hello', 'message_id': str(uuid.uuid4())}
    chat.agent_chat_send(request)
    chat.agent_chat_send(request)
    assert chat._agent_publisher.publish.call_count == 1
    envelope = json.loads(chat._agent_publisher.publish.call_args.args[0].data)
    assert envelope == request
    with pytest.raises(ValueError):
        chat.agent_chat_send({**request, 'text': 'different'})
    for payload in [[], {}, {'text': ''}, {'text': 'a'*4001}, {'text': 'ok', 'message_id': 'bad'}]:
        with pytest.raises(ValueError):
            chat.agent_chat_send(payload)
    request['message_id'] = str(uuid.uuid4())
    chat._motor_calibration_active = True
    with pytest.raises(RuntimeError, match='калибровку'):
        chat.agent_chat_send(request)
    chat._motor_calibration_active = False
    chat.count_subscribers.return_value = 0
    with pytest.raises(RuntimeError, match='подписчика'):
        chat.agent_chat_send(request)


def test_answers_status_plain_text_and_history_bound():
    chat = bare_chat()
    request = {'text': 'hi', 'message_id': str(uuid.uuid4())}
    chat.agent_chat_send(request)
    for answer, status, text in [(False, 'running', 'thinking'), (True, 'completed', 'hello'),
                                 (False, 'running', 'late')]:
        chat._agent_receive(String(data=json.dumps({**request, 'status': status, 'text': text})), answer=answer)
    result = chat.agent_chat_state()['messages'][0]
    assert result['answer'] == 'hello'
    assert result['status'] == 'completed'
    assert result['text'] == 'hi'
    for index in range(110):
        chat._agent_receive(String(data=f'plain answer {index}'), answer=True)
    history = chat.agent_chat_state()['messages']
    assert len(history) == 100
    assert history[-1]['answer'] == 'plain answer 109'
    assert history[-1]['text'] is None


def test_server_status_expiry_missing_bridge_and_sanitization():
    chat = bare_chat()
    assert chat.fleet_connection_state()['state'] == 'waiting'
    message = {'state':'connected','connected':True,'subscribed':True,
               'availability_confirmed':True,'host':'mqtt.test','port':1883,
               'password':'do-not-expose','robot_id':'test'}
    chat._fleet_connection_received(String(data=json.dumps(message)))
    assert chat.fleet_connection_state()['ready']
    assert 'password' not in chat.fleet_connection_state()
    chat._fleet_received_at -= 6
    assert chat.fleet_connection_state()['state'] == 'stale'
    assert not chat.fleet_connection_state()['ready']
    chat.count_publishers.return_value = 0
    assert chat.fleet_connection_state()['state'] == 'unavailable'
    chat.count_publishers.return_value = 2
    assert chat.fleet_connection_state()['state'] == 'ambiguous'
    assert not chat.fleet_connection_state()['ready']
    chat.count_publishers.return_value = 1
    chat._fleet_connection_received(String(data=json.dumps({**message,'connected':False,'state':'disconnected'})))
    assert chat.fleet_connection_state()['state'] == 'disconnected'
    assert not chat.fleet_connection_state()['ready']


def test_server_commands_merge_with_reordered_answers_and_keep_web_source():
    chat = bare_chat()
    command = {'message_id':str(uuid.uuid4()), 'robot_id':'test-rover',
               'text':'Сообщи статус', 'status':'queued'}
    receipt = lambda value: chat._server_command_received(String(data=json.dumps(value)))
    receipt(command)
    revision = chat._agent_revision
    receipt(command)
    assert chat._agent_revision == revision
    assert len(chat._agent_messages) == 1
    assert chat._agent_messages[0]['source'] == 'server'
    receipt({**command, 'status':'sent'})
    chat._agent_receive(String(data=json.dumps({**command,'status':'running','text':'Думаю'})), answer=False)
    receipt(command)
    assert chat._agent_messages[0]['status'] == 'running'
    chat._agent_receive(String(data=json.dumps({**command,'status':'completed','text':'Готов'})), answer=True)
    receipt(command)
    assert chat._agent_messages[0]['answer'] == 'Готов'
    assert chat._agent_messages[0]['text'] == command['text']
    late = {**command,'message_id':str(uuid.uuid4())}
    chat._agent_receive(String(data=json.dumps({**late,'status':'completed','text':'Ответ раньше запроса'})), answer=True)
    receipt(late)
    assert chat._agent_messages[-1]['status'] == 'completed'
    assert chat._agent_messages[-1]['source'] == 'server'
    local = {'message_id':str(uuid.uuid4()),'text':'Локальный запрос'}
    chat.agent_chat_send(local)
    receipt({**command, **local})
    assert chat._agent_messages[-1]['source'] == 'web'
    for payload in ['not json', '[]', '{}', json.dumps({**command,'text':None})]:
        chat._server_command_received(String(data=payload))
    assert len(chat._agent_messages) == 3


def test_http_ros_agent_round_trip(tmp_path):
    """Use a fake ROS agent, no LLM, MCP, robot commands or external network."""
    topic = '/test_agent_' + uuid.uuid4().hex
    rclpy.init(args=['--ros-args', '-p', 'port:=0',
        '-p', f'agent_input_topic:={topic}/input',
        '-p', f'agent_answer_topic:={topic}/answer',
        '-p', f'agent_status_topic:={topic}/status',
        '-p', f'fleet_connection_topic:={topic}/connection',
        '-p', f'hackathon_files_root:={tmp_path}/files',
        '-p', f'plans_directory:={tmp_path}/plans'])
    executor = SingleThreadedExecutor()
    gateway = agent = worker = None
    try:
        gateway = RoverWebGateway()
        agent = Node('test_agent')
        received = []
        answer = agent.create_publisher(String, topic+'/answer', 10)
        status = agent.create_publisher(String, topic+'/status', 10)
        connection = agent.create_publisher(String, topic+'/connection', 10)
        connection_state = dict(state='connected', connected=True, subscribed=True,
            availability_confirmed=True, host='test-broker', port=1883, robot_id='test-rover')
        agent.create_timer(.1, lambda: connection.publish(String(data=json.dumps(connection_state))))

        def receive(msg):
            command = json.loads(msg.data)
            received.append(command)
            status.publish(String(data=json.dumps({**command, 'status': 'running', 'text': 'Thinking'})))
            answer.publish(String(data=json.dumps({**command, 'robot_id': 'test-rover',
                'status': 'completed', 'text': 'Test answer'})))

        agent.create_subscription(String, topic+'/input', receive, 10)
        executor.add_node(gateway)
        executor.add_node(agent)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{gateway._http_server.server_port}'

        def get():
            with urlopen(url+'/api/agent', timeout=5) as response:
                return json.load(response)

        def send(payload):
            with urlopen(Request(url+'/api/agent/send', data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'}), timeout=5) as response:
                return json.load(response)

        deadline = time.monotonic()+8
        while not get()['input_subscribers'] and time.monotonic() < deadline:
            time.sleep(.1)
        request = {'text': 'test only', 'message_id': str(uuid.uuid4())}
        assert send(request)['ok']
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            messages = get()['messages']
            if messages and messages[0]['answer'] is not None:
                break
            time.sleep(.1)
        assert messages[0]['answer'] == 'Test answer'
        assert messages[0]['robot_id'] == 'test-rover'
        assert messages[0]['status'] == 'completed'
        assert send(request)['ok']
        assert len(received) == 1
        deadline = time.monotonic()+5
        while not get()['server_connection']['ready'] and time.monotonic() < deadline:
            time.sleep(.1)
        assert get()['server_connection']['ready']
        assert get()['server_connection']['host'] == 'test-broker'
        connection_state.update(connected=False, state='disconnected')
        deadline = time.monotonic()+5
        while get()['server_connection']['ready'] and time.monotonic() < deadline:
            time.sleep(.1)
        assert get()['server_connection']['state'] == 'disconnected'
        with pytest.raises(HTTPError) as error:
            send({'text': '', 'message_id': str(uuid.uuid4())})
        assert error.value.code == 400
    finally:
        executor.shutdown(timeout_sec=3)
        if worker: worker.join(timeout=3)
        if gateway: gateway.destroy_node()
        if agent: agent.destroy_node()
        rclpy.shutdown()
