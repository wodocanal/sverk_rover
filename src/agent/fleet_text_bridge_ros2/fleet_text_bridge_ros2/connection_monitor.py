"""ROS heartbeat for the actual MQTT session; never exposes credentials."""
import json
import threading
import time

from std_msgs.msg import String


class ConnectionMonitorMixin:
    def init_connection_monitor(self):
        self.declare_parameter('connection_topic', '/fleet/connection')
        self._connection_lock = threading.RLock()
        self._connection = dict(
            connected=False, subscribed=False, availability_confirmed=False,
            state='connecting', error='', connected_at=None, last_command_at=None,
            robot_id=self.robot_id,
            host=str(self.get_parameter('mqtt_host').value),
            port=int(self.get_parameter('mqtt_port').value),
        )
        self._connection_sub_mid = None
        self._connection_availability_mid = None
        self._connection_pub = self.create_publisher(
            String, str(self.get_parameter('connection_topic').value), 10)
        self.create_timer(1.0, self._publish_connection_status)

    def _connection_changed(self, **values):
        with self._connection_lock:
            self._connection.update(values)

    def _connection_started(self, client, rc):
        with self._connection_lock:
            self._connection_sub_mid = None
            self._connection_availability_mid = None
            self._connection.update(connected=rc == 0, subscribed=False,
                availability_confirmed=False, state='connecting' if rc == 0 else 'error',
                error='' if rc == 0 else f'MQTT CONNACK rc={rc}',
                connected_at=time.time() if rc == 0 else None)
            if rc != 0:
                return
            result, mid = client.subscribe(self.command_mqtt_topic, qos=1)
            if result != 0:
                self._connection.update(state='error', error=f'MQTT subscribe rc={result}')
            else:
                self._connection_sub_mid = mid
            published = client.publish(self.availability_mqtt_topic,
                json.dumps({'robot_id': self.robot_id, 'online': True}), qos=1, retain=True)
            if published.rc != 0:
                self._connection.update(state='error', error=f'MQTT availability publish rc={published.rc}')
            else:
                self._connection_availability_mid = published.mid

    def _on_mqtt_subscribe(self, client, userdata, mid, granted_qos, properties=None):
        with self._connection_lock:
            if mid != self._connection_sub_mid:
                return
            accepted = bool(granted_qos) and all(int(code) < 128 for code in granted_qos)
            self._connection['subscribed'] = accepted
            if not accepted:
                self._connection.update(state='error', error='MQTT broker rejected command subscription')
            self._connection_ready()

    def _on_mqtt_publish(self, client, userdata, mid, properties=None):
        with self._connection_lock:
            if mid == self._connection_availability_mid:
                self._connection['availability_confirmed'] = True
                self._connection_ready()

    def _connection_ready(self):
        if (self._connection['connected'] and self._connection['subscribed']
                and self._connection['availability_confirmed'] and not self._connection['error']):
            self._connection['state'] = 'connected'

    def _on_mqtt_connect_fail(self, client, userdata):
        self._connection_changed(connected=False, subscribed=False, availability_confirmed=False,
            state='disconnected', error='MQTT connection attempt failed; retrying')

    def _publish_connection_status(self):
        with self._connection_lock:
            data = dict(self._connection)
        if not self._mqtt.is_connected():
            data.update(connected=False, subscribed=False, availability_confirmed=False)
            if data['state'] == 'connected':
                data['state'] = 'disconnected'
        data['timestamp'] = time.time()
        self._connection_pub.publish(String(data=json.dumps(data)))
