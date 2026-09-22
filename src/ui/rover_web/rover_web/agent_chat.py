"""Bounded, in-memory ROS agent conversation shared by web clients."""
import json
import threading
import time
import uuid

from std_msgs.msg import String


class AgentChatMixin:
    def init_agent_chat(self):
        self._agent_lock = threading.RLock()
        self._agent_messages = []
        self._agent_instance = str(uuid.uuid4())
        self._agent_revision = 0
        self._fleet_connection = None
        self._fleet_received_at = None
        self.declare_parameter('fleet_connection_topic', '/fleet/connection')
        self.fleet_connection_topic = str(self.get_parameter('fleet_connection_topic').value)
        self.create_subscription(String, self.fleet_connection_topic, self._fleet_connection_received, 10)
        self.declare_parameter('fleet_received_command_topic', '/fleet/received_command')
        self.fleet_received_command_topic = str(self.get_parameter('fleet_received_command_topic').value)
        self.create_subscription(String, self.fleet_received_command_topic, self._server_command_received, 10)
        self._agent_topics = {}
        for key, default in (
            ('input', '/agent/text_command'),
            ('answer', '/agent/answer'),
            ('status', '/agent/status'),
        ):
            self.declare_parameter(f'agent_{key}_topic', default)
            self._agent_topics[key] = str(self.get_parameter(f'agent_{key}_topic').value)
        self._agent_publisher = self.create_publisher(String, self._agent_topics['input'], 10)
        self.create_subscription(String, self._agent_topics['answer'],
                                 lambda msg: self._agent_receive(msg, answer=True), 10)
        self.create_subscription(String, self._agent_topics['status'],
                                 lambda msg: self._agent_receive(msg, answer=False), 10)

    def _server_command_received(self, message):
        try:
            payload = json.loads(message.data)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        if any(not isinstance(payload.get(key), str) or not payload[key].strip()
               for key in ('message_id', 'robot_id', 'text')):
            return
        message_id = payload['message_id']
        if len(message_id) > 128 or payload.get('status') not in ('queued', 'sent'):
            return
        with self._agent_lock:
            entry = next((item for item in self._agent_messages if item['message_id'] == message_id), None)
            if entry is not None and entry.get('source') == 'web':
                return
            if entry is None:
                entry = {'message_id': message_id, 'created_at': time.time(), 'answer': None,
                         'status': 'queued', 'status_text': 'Получено от сервера; ожидает передачи агенту.'}
                self._agent_messages.append(entry)
            before = dict(entry)
            entry.update(text=payload['text'][:16000], robot_id=payload['robot_id'][:128], source='server')
            # DDS can deliver an answer before the receipt from a different topic.
            # Late receipt/dispatch notifications must not undo agent progress.
            if entry.get('status') == 'queued' and payload['status'] == 'sent' and entry['answer'] is None:
                entry.update(status='sent', status_text='Передано агенту; ожидаем подтверждения.')
            self._agent_messages = self._agent_messages[-100:]
            if entry != before:
                self._agent_revision += 1

    def _agent_receive(self, message, *, answer):
        raw = message.data[:16000]
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict):
            payload = {'text': raw}
        message_id = str(payload.get('message_id') or '')[:128]
        text = str(payload.get('text', payload.get('reply', raw)))[:16000]
        status = str(payload.get('status') or ('completed' if answer else 'running'))[:80]
        with self._agent_lock:
            entry = next((item for item in self._agent_messages
                          if message_id and item['message_id'] == message_id), None)
            if entry is None:
                entry = {'message_id': message_id or str(uuid.uuid4()), 'text': None,
                         'created_at': time.time(), 'answer': None, 'source': 'external'}
                self._agent_messages.append(entry)
            # Late status events must not overwrite a final answer.
            if answer or entry['answer'] is None:
                entry['status'] = status
                entry['status_text'] = text
            if answer:
                entry['answer'] = text
            entry['robot_id'] = str(payload.get('robot_id') or entry.get('robot_id') or '')[:128]
            self._agent_messages = self._agent_messages[-100:]
            self._agent_revision += 1

    def agent_chat_state(self):
        with self._agent_lock:
            return {
                'instance_id': self._agent_instance,
                'revision': self._agent_revision,
                'topics': dict(self._agent_topics),
                'server_input_topic': self.fleet_received_command_topic,
                'input_subscribers': self.count_subscribers(self._agent_topics['input']),
                'answer_publishers': self.count_publishers(self._agent_topics['answer']),
                'messages': [dict(item) for item in self._agent_messages],
                'server_connection': self.fleet_connection_state(),
            }

    def _fleet_connection_received(self, message):
        try:
            data = json.loads(message.data)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict) or not isinstance(data.get('connected'), bool):
            return
        # Explicit allowlist: a ROS publisher cannot accidentally expose passwords through this API.
        with self._agent_lock:
            self._fleet_connection = {
                key: str(data.get(key) or '')[:256]
                for key in ('host', 'robot_id', 'state', 'error')
            }
            self._fleet_connection.update({key: data.get(key) is True
                for key in ('connected', 'subscribed', 'availability_confirmed')})
            for key in ('port', 'connected_at', 'last_command_at'):
                value = data.get(key)
                self._fleet_connection[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            self._fleet_received_at = time.monotonic()

    def fleet_connection_state(self):
        with self._agent_lock:
            data = dict(self._fleet_connection or {})
            age = None if self._fleet_received_at is None else time.monotonic() - self._fleet_received_at
        publishers = self.count_publishers(self.fleet_connection_topic)
        if not publishers:
            data.update(state='unavailable', connected=False)
        elif age is None:
            data.update(state='waiting', connected=False)
        elif age > 5.0:
            data.update(state='stale', connected=False)
        data.update(topic=self.fleet_connection_topic, age_sec=age,
                    ready=bool(publishers == 1 and age is not None and age <= 5.0
                               and data.get('connected') and data.get('subscribed')
                               and data.get('availability_confirmed') and data.get('state') == 'connected'))
        if publishers > 1:
            data.update(state='ambiguous', ready=False)
        return data

    def agent_chat_send(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Expected a message object')
        text = payload.get('text')
        message_id = payload.get('message_id')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('Сообщение должно содержать от 1 до 4000 символов')
        try:
            message_id = str(uuid.UUID(message_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('message_id must be a UUID') from None
        text = text.strip()
        with self._agent_lock:
            existing = next((item for item in self._agent_messages
                             if item['message_id'] == message_id), None)
            if existing:
                if existing['text'] != text:
                    raise ValueError('message_id is already used for another message')
                return {'ok': True, 'message_id': message_id}
            if self._motor_calibration_active:
                raise RuntimeError('Завершите калибровку моторов перед отправкой команд агенту')
            if not self.count_subscribers(self._agent_topics['input']):
                raise RuntimeError('Нет подписчика на входной топик агента. Запустите агента.')
            # Omit robot_id: the agent uses its own configured identity in replies.
            command = String(data=json.dumps({'message_id': message_id, 'text': text},
                                            ensure_ascii=False))
            self._agent_publisher.publish(command)
            self._agent_messages.append({
                'message_id': message_id, 'text': text, 'answer': None,
                'status': 'sent', 'status_text': 'Опубликовано в ROS; ожидаем подтверждения агента.',
                'created_at': time.time(), 'robot_id': '',
                'source': 'web',
            })
            self._agent_messages = self._agent_messages[-100:]
            self._agent_revision += 1
        return {'ok': True, 'message_id': message_id}
