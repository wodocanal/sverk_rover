from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
import uuid

import yaml
from rover_configuration import config_path
from rover_device_manager.web_setup import WebDeviceSetup
from .system_services import service_status, restart_web_unit, control_unit, service_control_permissions, UNITS


class MaintenanceMixin:
    def init_maintenance(self):
        self._maintenance_lock = threading.RLock()
        self._motor_calibration_active = False
        self._web_instance_id = uuid.uuid4().hex
        self._web_restart_state = 'idle'
        self._web_restart_error = ''
        with open(config_path('rover_device_manager', 'device_manager.yaml')) as stream:
            config = yaml.safe_load(stream) or {}
        default = config.get('device_manager', {}).get('device_config', '~/.config/rover/devices.json')
        self.declare_parameter('device_setup_config', default)
        self.device_setup = WebDeviceSetup(str(self.get_parameter('device_setup_config').value).strip() or default,
                                           self._device_setup_guard)

    def _device_setup_guard(self):
        if Path('/run/systemd/system').is_dir():
            state = subprocess.run(['systemctl', 'is-active', 'rover-bringup.service'],
                                   capture_output=True, text=True, timeout=3).stdout.strip()
            if state not in ('inactive', 'failed', 'unknown'):
                raise RuntimeError(f'Stop rover-bringup before serial setup (state: {state})')
        active = [name for name in ('/wheel/encoders', '/imu/data', '/scan', '/scan_filtered')
                  if self.count_publishers(name)]
        if active or self._node_is_visible('/base_driver_node'):
            raise RuntimeError('Stop rover-bringup and other hardware launches before setup: '
                               + ', '.join(active))

    def motor_calibration_command(self, payload):
        command = str(payload.get('command', 'status'))
        if command not in ('status', 'begin', 'pulse', 'record', 'save', 'stop', 'end'):
            raise ValueError('Unknown calibration command')
        with self._maintenance_lock:
            if command not in ('status', 'stop') and self._web_restart_state in ('scheduled', 'restarting'):
                raise RuntimeError('Wait for rover-web restart to finish')
            if command == 'begin':
                if payload.get('wheels_raised') is not True:
                    raise ValueError('Confirm that all wheels are raised off the ground')
                if (self.navigation_status_payload()['running']
                        or self.motion_status_payload()['running']
                        or self._node_is_visible('/bt_navigator')):
                    raise RuntimeError('Stop navigation and motion plans before motor calibration')
                self.stop_drive()
            handle = self._ensure_service_client('/drive/calibrate_motors',
                                                  'rover_interfaces/srv/CalibrateMotors')
            if not handle.client.service_is_ready():
                if command == 'status':
                    return dict(available=False, active=self._motor_calibration_active,
                                message='Base driver calibration service is unavailable')
                raise RuntimeError('Start the updated base driver to use motor calibration')
            request = handle.srv_class.Request()
            request.command = command
            request.wheels_raised = payload.get('wheels_raised') is True
            request.wheel = int(payload.get('wheel', 0))
            request.direction = int(payload.get('direction', 0))
            response = self._wait_for_future(handle.client.call_async(request), timeout_sec=3.0,
                                             label='motor calibration')
            state = json.loads(response.state_json)
            self._motor_calibration_active = bool(state.get('active'))
            if not response.success:
                raise ValueError(response.message)
            if command != 'status':
                self.record_activity('calibration', command, {'message': response.message})
            return dict(available=True, **state)

    def maintenance_status(self):
        try:
            motors = self.motor_calibration_command({'command': 'status'})
        except Exception as exc:
            motors = dict(available=False, active=self._motor_calibration_active, message=str(exc))
        return {'motors': motors, 'devices': self.device_setup.status()}

    def device_setup_command(self, payload):
        with self._maintenance_lock:
            if self._web_restart_state in ('scheduled', 'restarting'):
                raise RuntimeError('Wait for rover-web restart to finish')
            command = payload.get('command')
            if command == 'begin':
                self.device_setup.begin(payload.get('confirmed'))
            elif command == 'probe':
                self.device_setup.probe(str(payload.get('role', '')), str(payload.get('device', '')))
            elif command == 'accept':
                self.device_setup.accept()
            elif command == 'save':
                self.device_setup.save()
            elif command == 'cancel':
                self.device_setup.cancel()
            else:
                raise ValueError('Unknown device setup command')
            self.record_activity('device_setup', str(command), {})
            return self.device_setup.status()

    def hardware_service_command(self, payload):
        action = payload.get('action')
        if action not in ('start', 'stop', 'restart') or payload.get('confirmed') is not True:
            raise ValueError('Confirm start/stop of rover-bringup')
        with self._maintenance_lock:
            if self._web_restart_state in ('scheduled', 'restarting'):
                raise RuntimeError('Wait for rover-web restart to finish')
            if self.device_setup.busy:
                raise RuntimeError('Wait for serial verification to finish before controlling bringup')
            if action in ('start', 'restart') and self.device_setup.phase not in ('idle', 'saved'):
                raise RuntimeError('Save or cancel Device Manager setup first')
            if action in ('stop', 'restart'):
                self.stop_navigation_runtime()
                self.stop_motion()
                self.stop_drive()
                try:
                    self.motor_calibration_command({'command': 'stop'})
                except Exception:
                    pass
            actions = ('stop', 'start') if action == 'restart' else (action,)
            for verb in actions:
                control_unit(UNITS['bringup'], verb)
            self._motor_calibration_active = False
            self.record_activity('maintenance', f'rover-bringup {action}', {})
            return {'ok': True, 'message': f'rover-bringup: {action}'}

    def system_services_status(self):
        return dict(services=service_status(), instance_id=self._web_instance_id,
                    permissions=service_control_permissions(),
                    web_restart=dict(state=self._web_restart_state, error=self._web_restart_error))

    def restart_web_service(self, payload):
        if payload.get('confirmed') is not True:
            raise ValueError('Confirm rover-web restart')
        with self._maintenance_lock:
            if self._web_restart_state in ('scheduled', 'restarting'):
                raise RuntimeError('Web restart is already scheduled')
            web = service_status()['web']
            if not web['available'] or not web['managed_current_process']:
                raise RuntimeError(web['error'] or 'This web process is not managed by rover-web.service')
            if self.device_setup.busy or self.device_setup.phase not in ('idle', 'saved'):
                raise RuntimeError('Save or cancel Device Manager setup before restarting web')
            self.stop_navigation_runtime()
            self.stop_motion()
            self.stop_drive()
            try:
                self.motor_calibration_command({'command': 'stop'})
            except Exception:
                pass
            self._web_restart_state, self._web_restart_error = 'scheduled', ''
            self.record_activity('maintenance', 'rover-web restart requested', {})
            # Let the HTTP response reach the browser before systemd stops us.
            timer = threading.Timer(1.0, self._restart_web_worker)
            timer.daemon = True
            timer.start()
            return dict(ok=True, instance_id=self._web_instance_id, restarting=True)

    def _restart_web_worker(self):
        self._web_restart_state = 'restarting'
        try:
            restart_web_unit()
        except Exception as exc:
            self._web_restart_state, self._web_restart_error = 'error', str(exc)
            self.get_logger().error(f'Cannot restart rover-web: {exc}')
