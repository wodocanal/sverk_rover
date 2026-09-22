"""HTTP settings adapter for the package-owned MQTT transport."""
from pathlib import Path
import threading

from fleet_text_bridge_ros2.runtime_settings import (
    DEFAULT_SETTINGS_FILE, PUBLIC_KEYS, load_overrides, package_defaults, save_overrides, validate,
)


class ServerSettingsMixin:
    def init_server_settings(self):
        self.declare_parameter('fleet_settings_file', DEFAULT_SETTINGS_FILE)
        self.declare_parameter('fleet_bridge_node_name', '/fleet_text_bridge')
        self.fleet_settings_file = str(Path(self.get_parameter('fleet_settings_file').value).expanduser().resolve())
        self.fleet_bridge_node_name = str(self.get_parameter('fleet_bridge_node_name').value).rstrip('/')
        self._server_settings_lock = threading.RLock()

    def _bridge_settings(self):
        from .web_gateway_node import parameter_value_to_python
        client = self._ensure_parameter_client(self.fleet_bridge_node_name)
        if not client.wait_for_services(timeout_sec=0.2):
            return None
        names = [*PUBLIC_KEYS, 'connection_settings_file', 'robot_id']
        response = self._wait_for_future(client.get_parameters(names), timeout_sec=2.0, label='bridge settings')
        values = {key: parameter_value_to_python(value) for key, value in zip(names, response.values)}
        if not values.get('connection_settings_file'):
            return None
        return values

    def server_settings_payload(self):
        with self._server_settings_lock:
            current = self._bridge_settings()
            base = {key: current[key] for key in PUBLIC_KEYS} if current else package_defaults()
            overrides = load_overrides(self.fleet_settings_file)
            settings = {**base, **{key: value for key, value in overrides.items() if key in PUBLIC_KEYS}}
            matching_file = current is not None and str(Path(current['connection_settings_file']).expanduser().resolve()) == self.fleet_settings_file
            return {
                'settings': settings, 'file': self.fleet_settings_file,
                'bridge_available': bool(current), 'can_reconnect': matching_file,
                'robot_id': current.get('robot_id', '') if current else '',
                'password_source': ('saved' if overrides['mqtt_password'] else 'empty') if 'mqtt_password' in overrides else 'environment',
                'connection': self.fleet_connection_state(),
                'notice': 'Web and bridge settings file paths differ; check launch configuration.' if current and not matching_file else '',
            }

    def update_server_settings(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'settings', 'clear_password', 'reconnect'}:
            raise ValueError('Unknown server settings request')
        values = validate(payload.get('settings'))
        if set(PUBLIC_KEYS) - set(values):
            raise ValueError('All public MQTT settings are required')
        for key in ('clear_password', 'reconnect'):
            if key in payload and type(payload[key]) is not bool:
                raise ValueError(f'{key}: expected boolean')
        if payload.get('clear_password') and values.get('mqtt_password'):
            raise ValueError('Cannot set and clear the password at the same time')
        with self._server_settings_lock:
            saved = load_overrides(self.fleet_settings_file)
            # A blank password field preserves the previous secret/environment fallback.
            if not values.get('mqtt_password'):
                values.pop('mqtt_password', None)
            if payload.get('clear_password'):
                values['mqtt_password'] = ''
            save_overrides({**saved, **values}, self.fleet_settings_file)
            reconnect = {'started': False, 'message': 'Saved. Applied on next bridge start or reconnect.'}
            if payload.get('reconnect'):
                try:
                    current = self._bridge_settings()
                    if current is None:
                        raise RuntimeError('Bridge is not running or needs updating. Settings are saved for its next start.')
                    if str(Path(current['connection_settings_file']).expanduser().resolve()) != self.fleet_settings_file:
                        raise RuntimeError('Web and bridge use different settings files. Connection was not restarted.')
                    handle = self._ensure_service_client(f'{self.fleet_bridge_node_name}/reconnect', 'std_srvs/srv/Trigger')
                    if not handle.client.wait_for_service(timeout_sec=0.5):
                        raise RuntimeError('MQTT reconnect service is unavailable.')
                    result = self._wait_for_future(handle.client.call_async(handle.srv_class.Request()),
                                                  timeout_sec=6.0, label='MQTT reconnect')
                    reconnect = {'started': bool(result.success), 'message': result.message}
                except RuntimeError as exc:
                    reconnect['message'] = str(exc)
            self.record_activity('server', 'MQTT settings saved', {'reconnect_started': reconnect['started']})
            result = self.server_settings_payload()
            result['reconnect'] = reconnect
            return result
