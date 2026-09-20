from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest

from rover_web import maintenance, system_services


def test_status_reports_unavailable_without_systemd(monkeypatch):
    monkeypatch.setattr(system_services.Path, 'is_dir', lambda _self: False)
    monkeypatch.setattr(system_services.Path, 'read_text', lambda _self: '0::/docker/test')
    run = Mock()
    monkeypatch.setattr(system_services.subprocess, 'run', run)
    status = system_services.service_status()
    assert all(not unit['available'] for unit in status.values())
    assert not status['web']['managed_current_process']
    run.assert_not_called()


def test_status_uses_systemd_unit_states_and_current_cgroup(monkeypatch):
    monkeypatch.setattr(system_services.Path, 'is_dir', lambda _self: True)
    monkeypatch.setattr(system_services.Path, 'read_text', lambda _self: '0::/system.slice/rover-web.service\n')
    run = Mock(side_effect=[
        SimpleNamespace(returncode=0, stdout='LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0', stderr=''),
        SimpleNamespace(returncode=0, stdout='LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=42', stderr=''),
    ])
    monkeypatch.setattr(system_services.subprocess, 'run', run)
    status = system_services.service_status()
    assert status['bringup']['active_state'] == 'inactive'
    assert status['web']['managed_current_process']
    assert status['web']['main_pid'] == 42
    assert [call.args[0][2] for call in run.call_args_list] == list(system_services.UNITS.values())


def test_web_restart_submits_only_allowlisted_nonblocking_job(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='', stderr=''))
    monkeypatch.setattr(system_services.subprocess, 'run', run)
    system_services.restart_web_unit()
    assert run.call_args.args[0] == ['systemctl', '--no-ask-password', '--no-block', 'restart', 'rover-web.service']
    run.return_value.returncode = 1
    run.return_value.stderr = 'Access denied'
    with pytest.raises(RuntimeError, match='Access denied'):
        system_services.restart_web_unit()


def gateway():
    return SimpleNamespace(
        _maintenance_lock=threading.RLock(), _web_instance_id='old-instance',
        _web_restart_state='idle', _web_restart_error='',
        device_setup=SimpleNamespace(busy=False, phase='idle'),
        stop_navigation_runtime=Mock(), stop_motion=Mock(), stop_drive=Mock(),
        motor_calibration_command=Mock(), record_activity=Mock(), _restart_web_worker=Mock(),
    )


def test_restart_acknowledges_before_deferred_job_and_rejects_duplicate(monkeypatch):
    node = gateway()
    monkeypatch.setattr(maintenance, 'service_status', lambda: {'web': {
        'available': True, 'managed_current_process': True, 'error': ''}})
    timer = Mock()
    monkeypatch.setattr(maintenance.threading, 'Timer', timer)
    result = maintenance.MaintenanceMixin.restart_web_service(node, {'confirmed': True})
    assert result['instance_id'] == 'old-instance'
    assert node._web_restart_state == 'scheduled'
    node._restart_web_worker.assert_not_called()
    timer.assert_called_once_with(1.0, node._restart_web_worker)
    timer.return_value.start.assert_called_once()
    node.stop_navigation_runtime.assert_called_once()
    with pytest.raises(RuntimeError, match='already scheduled'):
        maintenance.MaintenanceMixin.restart_web_service(node, {'confirmed': True})


def test_restart_requires_confirmation_and_preserves_unsaved_setup(monkeypatch):
    node = gateway()
    with pytest.raises(ValueError):
        maintenance.MaintenanceMixin.restart_web_service(node, {})
    monkeypatch.setattr(maintenance, 'service_status', lambda: {'web': {
        'available': True, 'managed_current_process': True, 'error': ''}})
    node.device_setup.phase = 'verified'
    with pytest.raises(RuntimeError, match='Save or cancel'):
        maintenance.MaintenanceMixin.restart_web_service(node, {'confirmed': True})
    node.stop_drive.assert_not_called()


def test_restart_failure_remains_visible_for_browser_polling(monkeypatch):
    node = gateway()
    node.get_logger = Mock(return_value=Mock())
    monkeypatch.setattr(maintenance, 'restart_web_unit', Mock(side_effect=RuntimeError('Access denied')))
    maintenance.MaintenanceMixin._restart_web_worker(node)
    assert node._web_restart_state == 'error'
    assert node._web_restart_error == 'Access denied'
