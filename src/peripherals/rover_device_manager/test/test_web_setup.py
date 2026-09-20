import time
import pytest
from rover_device_manager import web_setup as module


def test_setup_requires_new_verified_ports_and_explicit_save(tmp_path, monkeypatch):
    ports = {}
    monkeypatch.setattr(module, 'physical_serial_devices', lambda: dict(ports))
    monkeypatch.setattr(module, 'port_users', lambda _device: [])
    monkeypatch.setattr(module, '_config_entry', lambda result: dict(device=result.device, baudrate=115200))
    monkeypatch.setattr(module, 'verify_device', lambda role, device: module.DeviceResult(
        role=role, device=device, resolved_device=device, baudrate=115200,
        confidence='test', reason='verified', protocol='test', profile='test'))
    path = tmp_path/'devices.json'
    wizard = module.WebDeviceSetup(str(path))
    with pytest.raises(ValueError): wizard.begin(False)
    wizard.begin(True)
    for i, role in enumerate(module.ROLE_LABELS):
        device = f'/dev/test{i}'
        with pytest.raises(ValueError): wizard.probe(role, device)
        ports[device] = device
        wizard.probe(role, device)
        for _ in range(100):
            if not wizard.busy: break
            time.sleep(0.01)
        assert wizard.phase == 'verified'
        assert not path.exists()
        wizard.accept()
    assert wizard.phase == 'complete'
    wizard.save()
    assert set(module.load_device_config(str(path))['devices']) == set(module.ROLE_LABELS)


def test_busy_ports_and_config_conflicts_do_not_overwrite(tmp_path, monkeypatch):
    ports = {}
    monkeypatch.setattr(module, 'physical_serial_devices', lambda: dict(ports))
    monkeypatch.setattr(module, 'port_users', lambda _device: ['123'])
    path = tmp_path/'devices.json'
    wizard = module.WebDeviceSetup(str(path))
    wizard.begin(True)
    ports['/dev/test'] = '/dev/test'
    with pytest.raises(RuntimeError, match='busy'): wizard.probe('imu', '/dev/test')
    wizard.phase = 'complete'
    path.write_text('external change')
    with pytest.raises(RuntimeError, match='changed externally'): wizard.save()
    assert path.read_text() == 'external change'


def test_cancel_never_saves_late_probe_result(tmp_path, monkeypatch):
    import threading
    ports = {}
    started, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(module, 'physical_serial_devices', lambda: dict(ports))
    monkeypatch.setattr(module, 'port_users', lambda _device: [])
    def probe(*_args):
        started.set()
        finish.wait(2)
        raise RuntimeError('probe canceled')
    monkeypatch.setattr(module, 'verify_device', probe)
    wizard = module.WebDeviceSetup(str(tmp_path/'devices.json'))
    wizard.begin(True)
    ports['/dev/test'] = '/dev/test'
    wizard.probe('imu', '/dev/test')
    assert started.wait(1)
    wizard.cancel()
    assert wizard.phase == 'canceling'
    finish.set()
    for _ in range(100):
        if not wizard.busy: break
        time.sleep(0.01)
    assert wizard.phase == 'idle' and wizard.pending is None
    assert not (tmp_path/'devices.json').exists()
