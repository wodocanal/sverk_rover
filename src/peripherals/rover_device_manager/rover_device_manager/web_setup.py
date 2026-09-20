"""Non-interactive device setup using the same protocol probes as the CLI."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import threading

from .discovery import (DEFAULT_DEVICE_CONFIG, DEFAULT_IMU_BAUDRATES,
                        DEFAULT_SLLIDAR_BAUDRATES, DeviceResult, load_device_config,
                        physical_serial_devices, preferred_stable_path,
                        probe_motor_controller, probe_sllidar, probe_yahboom_imu,
                        save_device_config)
from .setup_devices import ROLE_LABELS, _config_entry, _probe_sllidar_with_official_sdk


def port_users(device):
    resolved = os.path.realpath(device)
    users = set()
    for process in Path('/proc').glob('[0-9]*'):
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    if os.path.realpath(fd) == resolved:
                        users.add(process.name)
                except OSError:
                    continue
        except (OSError, PermissionError):
            continue
    return sorted(users)


def verify_device(role, device):
    stable = preferred_stable_path(device)
    if role == 'motor_controller':
        ok, reason = probe_motor_controller(stable, 115200)
        baudrate, profile, protocol, parameters = 115200, 'quad_md', 'quad_md_ascii', {}
    elif role == 'imu':
        ok, baudrate, reason = probe_yahboom_imu(stable, DEFAULT_IMU_BAUDRATES)
        profile, protocol, parameters = 'yb_mra02_v1', 'yahboom_serial', {}
    elif role == 'lidar':
        ok, baudrate, reason, profile, parameters = _probe_sllidar_with_official_sdk(stable)
        if not ok:
            ok, baudrate, reason, profile, parameters = probe_sllidar(stable, DEFAULT_SLLIDAR_BAUDRATES)
        protocol = 'sllidar_serial'
    else:
        raise ValueError('Unknown device role')
    if not ok:
        raise RuntimeError(reason)
    return DeviceResult(role=role, device=stable, resolved_device=os.path.realpath(stable),
                        baudrate=baudrate, confidence='setup_protocol_verified', reason=reason,
                        protocol=protocol, profile=profile, parameters=parameters)


class WebDeviceSetup:
    def __init__(self, config_path=DEFAULT_DEVICE_CONFIG, guard=lambda: None):
        self.config_path, self.guard = config_path, guard
        self.lock = threading.RLock()
        self.baseline = set()
        self.results = {}
        self.pending = None
        self.phase = 'idle'
        self.error = ''
        self.busy = False
        self.canceled = False
        self.original = None

    def _fingerprint(self):
        path = Path(self.config_path).expanduser()
        return path.read_bytes() if path.exists() else None

    def status(self):
        inventory = physical_serial_devices()
        try:
            saved = load_device_config(self.config_path)['devices']
            config_error = ''
        except RuntimeError as exc:
            saved, config_error = {}, str(exc)
        with self.lock:
            accepted = {entry['device'] for entry in self.results.values()}
            return dict(phase=self.phase, busy=self.busy, error=self.error,
                config_path=str(Path(self.config_path).expanduser()), config_error=config_error,
                roles=ROLE_LABELS, accepted=copy.deepcopy(self.results), saved=saved,
                pending=copy.deepcopy(self.pending),
                inventory=[dict(resolved=resolved, device=alias,
                    candidate=resolved not in self.baseline and alias not in accepted
                              and resolved not in {os.path.realpath(p) for p in accepted})
                    for resolved, alias in inventory.items()])

    def begin(self, confirmed):
        if confirmed is not True:
            raise ValueError('Stop bringup, raise wheels and disconnect the three serial devices first')
        self.guard()
        with self.lock:
            if self.busy:
                raise RuntimeError('Wait for the current probe to finish')
            self.baseline = set(physical_serial_devices())
            self.results, self.pending, self.error = {}, None, ''
            self.phase, self.canceled = 'waiting', False
            self.original = self._fingerprint()

    def probe(self, role, device):
        self.guard()
        with self.lock:
            if self.busy or self.phase not in ('waiting', 'error', 'verified'):
                raise RuntimeError('Start the setup wizard before probing')
            if role not in ROLE_LABELS or role in self.results:
                raise ValueError('Choose an unconfigured device role')
            available = physical_serial_devices()
            resolved = os.path.realpath(device)
            if resolved not in available or resolved in self.baseline:
                raise ValueError('Select a newly connected serial device from the list')
            if any(os.path.realpath(entry['device']) == resolved for entry in self.results.values()):
                raise ValueError('This port is already assigned')
            users = port_users(resolved)
            if users:
                raise RuntimeError(f'Serial port is busy; process IDs: {", ".join(users)}')
            self.busy, self.canceled = True, False
            self.pending, self.error, self.phase = None, '', 'probing'
            threading.Thread(target=self._probe, args=(role, available[resolved]), daemon=True).start()

    def _probe(self, role, device):
        try:
            result = verify_device(role, device)
            entry = _config_entry(result)
            with self.lock:
                if not self.canceled:
                    self.pending = dict(role=role, entry=entry)
                    self.phase = 'verified'
        except Exception as exc:
            with self.lock:
                if not self.canceled:
                    self.error, self.phase = str(exc), 'error'
        finally:
            with self.lock:
                self.busy = False
                if self.canceled:
                    self.phase = 'idle'

    def accept(self):
        self.guard()
        with self.lock:
            if self.busy or self.phase != 'verified' or not self.pending:
                raise ValueError('Verify a device first')
            entry = self.pending['entry']
            if os.path.realpath(entry['device']) not in physical_serial_devices():
                raise RuntimeError('Verified device was disconnected; reconnect and retry')
            self.results[self.pending['role']] = entry
            self.pending = None
            self.phase = 'complete' if len(self.results) == 3 else 'waiting'

    def save(self):
        self.guard()
        with self.lock:
            if self.busy or self.phase != 'complete':
                raise ValueError('Verify and accept all three devices before saving')
            if self._fingerprint() != self.original:
                raise RuntimeError('Device config changed externally; restart setup to avoid overwriting it')
            available = physical_serial_devices()
            if any(os.path.realpath(entry['device']) not in available for entry in self.results.values()):
                raise RuntimeError('An accepted device is disconnected')
            path = Path(self.config_path).expanduser()
            old = load_device_config(self.config_path)['devices'] if path.exists() else {}
            if path.exists():
                path.with_suffix('.json.bak').write_bytes(path.read_bytes())
            save_device_config({**old, **self.results}, self.config_path)
            self.phase = 'saved'

    def cancel(self):
        with self.lock:
            self.canceled = True
            self.pending, self.results = None, {}
            self.phase = 'canceling' if self.busy else 'idle'
