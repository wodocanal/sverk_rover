"""Reload only the MQTT transport, leaving the ROS bridge and agent running."""
import json
import os
from pathlib import Path

from rclpy.parameter import Parameter
from std_srvs.srv import Trigger

from .runtime_settings import DEFAULT_SETTINGS_FILE, PUBLIC_KEYS, load_overrides, validate


class ConnectionSettingsMixin:
    def init_connection_settings(self):
        self.declare_parameter('connection_settings_file', DEFAULT_SETTINGS_FILE)
        self.connection_settings_file = str(Path(
            self.get_parameter('connection_settings_file').value).expanduser().resolve())
        self._connection_defaults = {key: self.get_parameter(key).value for key in PUBLIC_KEYS}
        self._apply_connection_settings(self._read_connection_settings())
        self.create_service(Trigger, '~/reconnect', self._reconnect_service)

    def _read_connection_settings(self):
        defaults = dict(self._connection_defaults)
        password_env = str(self.get_parameter('mqtt_password_env').value)
        defaults['mqtt_password'] = os.getenv(password_env, os.getenv('FLEET_MQTT_PASSWORD', ''))
        return validate({**defaults, **load_overrides(self.connection_settings_file)})

    def _apply_connection_settings(self, values):
        self._mqtt_settings = values
        self.set_parameters([Parameter(key, value=values[key]) for key in PUBLIC_KEYS])
        self.prefix = values['mqtt_topic_prefix']
        for name in ('command', 'answer', 'status', 'availability'):
            setattr(self, f'{name}_mqtt_topic', f'{self.prefix}/{self.robot_id}/{name}')

    def _stop_transport(self):
        if self._mqtt.is_connected():
            published = self._mqtt.publish(self.availability_mqtt_topic,
                json.dumps({'robot_id': self.robot_id, 'online': False}), qos=1, retain=True)
            if published.rc == 0:
                published.wait_for_publish(timeout=1.0)
        self._mqtt.disconnect()
        self._mqtt.loop_stop()

    def _has_commands(self):
        return self._active_command is not None or bool(self._pending) or not self._incoming.empty()

    def _reconnect_service(self, request, response):
        if self._has_commands():
            response.success = False
            response.message = 'Bridge is processing commands; wait before reconnecting.'
            return response
        try:
            values = self._read_connection_settings()
            self._stop_transport()
            # A command can arrive between the initial check and stopping Paho's loop.
            if self._has_commands():
                self._start_transport()
                response.success = False
                response.message = 'A command arrived; previous connection restored. Retry after completion.'
                return response
            self._apply_connection_settings(values)
            self._connection_changed(connected=False, subscribed=False, availability_confirmed=False,
                state='connecting', error='', connected_at=None, last_command_at=None,
                host=values['mqtt_host'], port=values['mqtt_port'])
            self._start_transport()
            self._publish_connection_status()
            response.success = True
            response.message = 'MQTT reconnect started. Wait for broker confirmation on the Agent page.'
        except Exception:
            # Never send exception payloads that might include credentials to ROS or HTTP.
            response.success = False
            response.message = 'MQTT reconnect failed; check settings file and bridge status.'
        return response
