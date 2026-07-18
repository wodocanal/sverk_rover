from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import serial


YAHBOOM_FRAME_HEADER = 0x55
YAHBOOM_FRAME_LENGTH = 11
YAHBOOM_FRAME_TYPES = {0x51, 0x52, 0x53, 0x54}
DEFAULT_IMU_BAUDRATES = (921600, 115200, 57600, 38400, 19200, 9600)
DEFAULT_SLLIDAR_BAUDRATES = (460800, 115200, 256000, 1000000)
SLLIDAR_GET_INFO = b'\xA5\x50'
SLLIDAR_STOP = b'\xA5\x25'
SLLIDAR_ANSWER_SYNC = b'\xA5\x5A'
SLLIDAR_DEVICE_INFO_TYPE = 0x04
SLLIDAR_DEVICE_INFO_LENGTH = 20
DEFAULT_DEVICE_CONFIG = '~/.config/rover/devices.json'
CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DeviceResult:
    role: str
    device: str
    resolved_device: str
    baudrate: int
    confidence: str
    reason: str
    protocol: str = ''
    profile: str = ''
    parameters: dict[str, Any] = field(default_factory=dict)


def serial_candidates(extra: Iterable[str] = ()) -> list[str]:
    """Return one useful path for every physical serial device.

    /dev/serial/by-path is preferred because it follows the physical USB socket
    and therefore does not require unique serial numbers on a production fleet.
    """
    patterns = (
        '/dev/serial/by-path/*',
        '/dev/serial/by-id/*',
        '/dev/ttyUSB*',
        '/dev/ttyACM*',
    )
    raw: list[str] = []
    for pattern in patterns:
        raw.extend(sorted(glob.glob(pattern)))
    raw.extend(extra)

    result: list[str] = []
    seen: set[str] = set()
    for path in raw:
        try:
            resolved = os.path.realpath(path)
        except OSError:
            continue
        if not os.path.exists(resolved) or resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return result


def physical_serial_devices() -> dict[str, str]:
    """Map resolved tty paths to their preferred stable aliases."""
    return {
        os.path.realpath(path): preferred_stable_path(path)
        for path in serial_candidates()
    }


def preferred_stable_path(device: str) -> str:
    resolved = os.path.realpath(device)
    for pattern in ('/dev/serial/by-path/*', '/dev/serial/by-id/*'):
        for alias in sorted(glob.glob(pattern)):
            if os.path.realpath(alias) == resolved:
                return alias
    return resolved


def udev_properties(device: str) -> dict[str, str]:
    """Read useful USB metadata without making it part of runtime identity."""
    resolved = os.path.realpath(device)
    try:
        completed = subprocess.run(
            ['udevadm', 'info', '--query=property', f'--name={resolved}'],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    keep = {
        'ID_VENDOR_ID',
        'ID_MODEL_ID',
        'ID_VENDOR',
        'ID_MODEL',
        'ID_SERIAL',
        'ID_SERIAL_SHORT',
        'ID_PATH',
        'ID_PATH_TAG',
    }
    properties: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in keep:
            properties[key] = value
    return properties


def _valid_yahboom_frame(frame: bytes) -> bool:
    return (
        len(frame) == YAHBOOM_FRAME_LENGTH
        and frame[0] == YAHBOOM_FRAME_HEADER
        and frame[1] in YAHBOOM_FRAME_TYPES
        and (sum(frame[:10]) & 0xFF) == frame[10]
    )


def _scan_yahboom_frames(data: bytes) -> tuple[int, set[int]]:
    valid = 0
    frame_types: set[int] = set()
    index = 0
    while index + YAHBOOM_FRAME_LENGTH <= len(data):
        if data[index] != YAHBOOM_FRAME_HEADER:
            index += 1
            continue
        frame = data[index:index + YAHBOOM_FRAME_LENGTH]
        if _valid_yahboom_frame(frame):
            valid += 1
            frame_types.add(frame[1])
            index += YAHBOOM_FRAME_LENGTH
        else:
            index += 1
    return valid, frame_types


def probe_yahboom_imu(
    device: str,
    baudrates: Sequence[int] = DEFAULT_IMU_BAUDRATES,
) -> tuple[bool, int, str]:
    """Passively identify the Yahboom 0x55/11-byte IMU protocol."""
    failures: list[str] = []
    for baudrate in baudrates:
        try:
            with serial.Serial(
                device,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.04,
                write_timeout=0.4,
            ) as port:
                time.sleep(0.08)
                port.reset_input_buffer()
                deadline = time.monotonic() + 0.55
                data = bytearray()
                while time.monotonic() < deadline:
                    chunk = port.read(512)
                    if chunk:
                        data.extend(chunk)
                    if len(data) >= 220:
                        break

                valid, types = _scan_yahboom_frames(bytes(data))
                if valid >= 4 and 0x51 in types and 0x52 in types:
                    type_text = ','.join(
                        f'0x{value:02X}' for value in sorted(types)
                    )
                    return (
                        True,
                        baudrate,
                        f'Yahboom 0x55 frames verified: {valid} frames, '
                        f'types {type_text}',
                    )
                failures.append(
                    f'{baudrate}: {valid} valid frames from {len(data)} bytes'
                )
        except (OSError, serial.SerialException) as exc:
            failures.append(f'{baudrate}: {exc}')

    return False, 0, '; '.join(failures)


def _parse_sllidar_device_info(data: bytes) -> Optional[dict[str, Any]]:
    start = 0
    while True:
        index = data.find(SLLIDAR_ANSWER_SYNC, start)
        if index < 0 or index + 7 > len(data):
            return None

        descriptor = data[index:index + 7]
        size_and_subtype = int.from_bytes(descriptor[2:6], 'little')
        payload_size = size_and_subtype & 0x3FFFFFFF
        answer_type = descriptor[6]
        payload_start = index + 7
        payload_end = payload_start + payload_size

        if (
            answer_type == SLLIDAR_DEVICE_INFO_TYPE
            and payload_size == SLLIDAR_DEVICE_INFO_LENGTH
            and payload_end <= len(data)
        ):
            payload = data[payload_start:payload_end]
            firmware = int.from_bytes(payload[1:3], 'little')
            return {
                'model_code': int(payload[0]),
                'firmware': f'{firmware >> 8}.{firmware & 0xFF:02d}',
                'hardware_revision': int(payload[3]),
                'lidar_serial_number': payload[4:20].hex().upper(),
            }
        start = index + 1


def _sllidar_profile(baudrate: int) -> tuple[str, dict[str, Any]]:
    if baudrate == 460800:
        return 'c1', {
            'scan_mode': 'Standard',
            'range_min': 0.17,
            'scan_frequency': 10.0,
        }
    if baudrate == 115200:
        return 'serial_115200', {
            'scan_mode': 'Sensitivity',
            'range_min': 0.15,
            'scan_frequency': 10.0,
        }
    if baudrate == 256000:
        return 'serial_256000', {
            'scan_mode': 'Sensitivity',
            'range_min': 0.15,
            'scan_frequency': 10.0,
        }
    if baudrate == 1000000:
        return 'serial_1000000', {
            'scan_mode': 'DenseBoost',
            'range_min': 0.05,
            'scan_frequency': 10.0,
        }
    return 'serial', {
        'scan_mode': 'Standard',
        'range_min': 0.15,
        'scan_frequency': 10.0,
    }


def probe_sllidar(
    device: str,
    baudrates: Sequence[int] = DEFAULT_SLLIDAR_BAUDRATES,
) -> tuple[bool, int, str, str, dict[str, Any]]:
    """Identify a serial SLLIDAR and infer its runtime serial profile.

    STOP and GET_DEVICE_INFO do not start autonomous rover motion. The lidar
    motor can briefly react to serial/DTR state on some models, so the setup
    wizard still asks for a stationary, safely supported rover.
    """
    failures: list[str] = []
    for baudrate in baudrates:
        try:
            with serial.Serial(
                device,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.04,
                write_timeout=0.5,
            ) as port:
                time.sleep(0.10)
                try:
                    port.write(SLLIDAR_STOP)
                    port.flush()
                except serial.SerialException:
                    pass
                time.sleep(0.06)
                port.reset_input_buffer()

                data = bytearray()
                info: Optional[dict[str, Any]] = None
                for _attempt in range(2):
                    port.write(SLLIDAR_GET_INFO)
                    port.flush()
                    deadline = time.monotonic() + 0.85
                    while time.monotonic() < deadline:
                        chunk = port.read(256)
                        if chunk:
                            data.extend(chunk)
                            info = _parse_sllidar_device_info(bytes(data))
                            if info:
                                break
                    if info:
                        break

                try:
                    port.write(SLLIDAR_STOP)
                    port.flush()
                except serial.SerialException:
                    pass

                if info:
                    profile, parameters = _sllidar_profile(baudrate)
                    parameters = {**parameters, **info}
                    reason = (
                        'SLLIDAR device info verified: '
                        f"model {info['model_code']}, firmware {info['firmware']}, "
                        f"hardware {info['hardware_revision']}, "
                        f"serial {info['lidar_serial_number']}"
                    )
                    return True, baudrate, reason, profile, parameters
                failures.append(
                    f'{baudrate}: no valid device-info response '
                    f'({len(data)} bytes read)'
                )
        except (OSError, serial.SerialException) as exc:
            failures.append(f'{baudrate}: {exc}')

    return False, 0, '; '.join(failures), '', {}


def probe_motor_controller(
    device: str,
    baudrate: int = 115200,
) -> tuple[bool, str]:
    """Verify Quad-MD using feedback and an explicit zero-speed command."""
    try:
        with serial.Serial(
            device,
            baudrate=baudrate,
            timeout=0.05,
            write_timeout=0.5,
        ) as port:
            time.sleep(0.12)
            port.reset_input_buffer()
            port.write(b'$upload:1,0,1#')
            port.flush()

            deadline = time.monotonic() + 1.2
            data = bytearray()
            while time.monotonic() < deadline:
                chunk = port.read(256)
                if chunk:
                    data.extend(chunk)
                    text = data.decode('ascii', errors='ignore')
                    if '$MAll:' in text or '$MSPD:' in text:
                        try:
                            port.write(b'$upload:0,0,0#$spd:0,0,0,0#')
                            port.flush()
                        except serial.SerialException:
                            pass
                        return True, 'received Quad-MD $MAll/$MSPD feedback frame'

            try:
                port.write(b'$upload:0,0,0#$spd:0,0,0,0#')
                port.flush()
            except serial.SerialException:
                pass
            return False, f'no Quad-MD frame ({len(data)} bytes read)'
    except (OSError, serial.SerialException) as exc:
        return False, f'open/probe failed: {exc}'


def _make_link(link: Path, target: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(os.path.realpath(target))


def _clear_runtime(runtime: Path) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('motor_controller', 'imu', 'lidar', 'devices.json'):
        path = runtime / name
        if path.is_symlink() or path.exists():
            path.unlink()


def _write_runtime(
    runtime_dir: str,
    results: dict[str, DeviceResult],
) -> None:
    runtime = Path(runtime_dir)
    _clear_runtime(runtime)
    for role, result in results.items():
        _make_link(runtime / role, result.device)
    payload = {name: asdict(result) for name, result in results.items()}
    (runtime / 'devices.json').write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )


def expand_config_path(config_path: str = DEFAULT_DEVICE_CONFIG) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(config_path)))


def load_device_config(
    config_path: str = DEFAULT_DEVICE_CONFIG,
) -> dict[str, Any]:
    path = expand_config_path(config_path)
    if not path.exists():
        raise RuntimeError(
            f'Device configuration not found: {path}. Run: '
            'ros2 run rover_device_manager setup_devices'
        )
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'Cannot read device configuration {path}: {exc}') from exc
    if payload.get('schema_version') != CONFIG_SCHEMA_VERSION:
        raise RuntimeError(
            f'Unsupported device configuration schema in {path}: '
            f"{payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get('devices'), dict):
        raise RuntimeError(f'Invalid device configuration: {path}')
    return payload


def save_device_config(
    devices: dict[str, dict[str, Any]],
    config_path: str = DEFAULT_DEVICE_CONFIG,
) -> Path:
    path = expand_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'schema_version': CONFIG_SCHEMA_VERSION,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'identity_strategy': 'physical_usb_path',
        'devices': devices,
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + '\n'
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        dir=path.parent,
        prefix=f'.{path.name}.',
        delete=False,
    ) as temporary:
        temporary.write(serialized)
        temp_path = Path(temporary.name)
    os.chmod(temp_path, 0o600)
    temp_path.replace(path)
    return path


def _configured_results(
    config_path: str,
    require_imu: bool,
    require_lidar: bool,
) -> dict[str, DeviceResult]:
    payload = load_device_config(config_path)
    configured = payload['devices']
    required = ['motor_controller']
    if require_imu:
        required.append('imu')
    if require_lidar:
        required.append('lidar')

    results: dict[str, DeviceResult] = {}
    used: set[str] = set()
    for role in required:
        entry = configured.get(role)
        if not isinstance(entry, dict):
            raise RuntimeError(
                f'Role {role!r} is absent from {expand_config_path(config_path)}. '
                'Run the setup wizard again.'
            )
        device = str(entry.get('device', '')).strip()
        if not device or not os.path.exists(device):
            raise RuntimeError(
                f'Configured {role} path is unavailable: {device or "<empty>"}. '
                'Check USB cabling or rerun setup_devices.'
            )
        resolved = os.path.realpath(device)
        if resolved in used:
            raise RuntimeError(
                f'Configured path collision: {role} resolves to {resolved}, '
                'which is already assigned to another role.'
            )
        used.add(resolved)
        results[role] = DeviceResult(
            role=role,
            device=device,
            resolved_device=resolved,
            baudrate=int(entry.get('baudrate', 0)),
            confidence='configured_physical_path',
            reason='loaded from persistent setup configuration',
            protocol=str(entry.get('protocol', '')),
            profile=str(entry.get('profile', '')),
            parameters=dict(entry.get('parameters', {})),
        )
    return results


def verify_results(results: dict[str, DeviceResult]) -> dict[str, DeviceResult]:
    verified: dict[str, DeviceResult] = {}
    for role, result in results.items():
        if role == 'motor_controller':
            ok, reason = probe_motor_controller(result.device, result.baudrate)
            if not ok:
                raise RuntimeError(f'Configured motor controller failed verification: {reason}')
        elif role == 'imu':
            ok, baudrate, reason = probe_yahboom_imu(
                result.device,
                baudrates=(result.baudrate,),
            )
            if not ok:
                raise RuntimeError(f'Configured IMU failed verification: {reason}')
            result = DeviceResult(**{**asdict(result), 'baudrate': baudrate})
        elif role == 'lidar':
            ok, baudrate, reason, profile, parameters = probe_sllidar(
                result.device,
                baudrates=(result.baudrate,),
            )
            if not ok:
                raise RuntimeError(f'Configured lidar failed verification: {reason}')
            result = DeviceResult(
                **{
                    **asdict(result),
                    'baudrate': baudrate,
                    'profile': profile or result.profile,
                    'parameters': parameters or result.parameters,
                }
            )
        verified[role] = DeviceResult(
            **{
                **asdict(result),
                'confidence': 'configured_and_protocol_verified',
                'reason': reason,
            }
        )
    return verified


def prepare_devices(
    mode: str = 'configured',
    config_path: str = DEFAULT_DEVICE_CONFIG,
    runtime_dir: str = '/tmp/rover_devices',
    require_imu: bool = True,
    require_lidar: bool = False,
    motor_device: Optional[str] = None,
    imu_device: Optional[str] = None,
    lidar_device: Optional[str] = None,
    imu_baudrates: Sequence[int] = DEFAULT_IMU_BAUDRATES,
    lidar_baudrates: Sequence[int] = DEFAULT_SLLIDAR_BAUDRATES,
) -> dict[str, DeviceResult]:
    normalized = mode.strip().lower()
    if any((motor_device, imu_device, lidar_device)):
        normalized = 'full'
    if normalized == 'configured':
        results = _configured_results(config_path, require_imu, require_lidar)
    elif normalized == 'verify':
        results = verify_results(
            _configured_results(config_path, require_imu, require_lidar)
        )
    elif normalized == 'full':
        results = discover(
            runtime_dir=runtime_dir,
            require_imu=require_imu,
            require_lidar=require_lidar,
            motor_device=motor_device,
            imu_device=imu_device,
            lidar_device=lidar_device,
            imu_baudrates=imu_baudrates,
            lidar_baudrates=lidar_baudrates,
        )
        return results
    else:
        raise RuntimeError(
            f'Unknown discovery mode {mode!r}; use configured, verify or full'
        )

    _write_runtime(runtime_dir, results)
    return results


def discover(
    runtime_dir: str = '/tmp/rover_devices',
    require_imu: bool = True,
    require_lidar: bool = False,
    motor_device: Optional[str] = None,
    imu_device: Optional[str] = None,
    lidar_device: Optional[str] = None,
    imu_baudrates: Sequence[int] = DEFAULT_IMU_BAUDRATES,
    lidar_baudrates: Sequence[int] = DEFAULT_SLLIDAR_BAUDRATES,
) -> dict[str, DeviceResult]:
    """Full protocol discovery. Intended for diagnostics, not normal launch."""
    candidates = serial_candidates(
        path for path in (motor_device, imu_device, lidar_device) if path
    )
    if not candidates:
        raise RuntimeError(
            'No /dev/ttyUSB*, /dev/ttyACM* or serial aliases found'
        )

    results: dict[str, DeviceResult] = {}
    used_realpaths: set[str] = set()

    imu_search = [imu_device] if imu_device else candidates
    imu_failures: list[str] = []
    if require_imu or imu_device:
        for candidate in imu_search:
            if not candidate:
                continue
            ok, baudrate, reason = probe_yahboom_imu(
                candidate,
                baudrates=imu_baudrates,
            )
            if ok:
                resolved = os.path.realpath(candidate)
                results['imu'] = DeviceResult(
                    role='imu',
                    device=preferred_stable_path(candidate),
                    resolved_device=resolved,
                    baudrate=baudrate,
                    confidence='protocol_verified',
                    reason=reason,
                    protocol='yahboom_0x55',
                    profile='yahboom_10_axis',
                )
                used_realpaths.add(resolved)
                break
            imu_failures.append(f'{candidate}: {reason}')

        if require_imu and 'imu' not in results:
            details = '; '.join(imu_failures) or 'no candidates'
            raise RuntimeError(f'Yahboom 10-axis IMU not detected. {details}')

    # Check Quad-MD before sending SLLIDAR binary commands to all remaining
    # ports. This avoids treating a continuous $MAll/$MSPD stream as lidar data.
    motor_search = [motor_device] if motor_device else candidates
    motor_failures: list[str] = []
    for candidate in motor_search:
        if not candidate:
            continue
        resolved = os.path.realpath(candidate)
        if resolved in used_realpaths:
            continue
        ok, reason = probe_motor_controller(candidate)
        if ok:
            results['motor_controller'] = DeviceResult(
                role='motor_controller',
                device=preferred_stable_path(candidate),
                resolved_device=resolved,
                baudrate=115200,
                confidence='protocol_verified',
                reason=reason,
                protocol='quad_md_ascii',
                profile='quad_md',
            )
            used_realpaths.add(resolved)
            break
        motor_failures.append(f'{candidate}: {reason}')

    if 'motor_controller' not in results:
        details = '; '.join(motor_failures) or 'no candidates'
        raise RuntimeError(f'Motor controller not detected. {details}')

    lidar_search = [lidar_device] if lidar_device else candidates
    lidar_failures: list[str] = []
    if require_lidar or lidar_device:
        for candidate in lidar_search:
            if not candidate:
                continue
            resolved = os.path.realpath(candidate)
            if resolved in used_realpaths:
                continue
            ok, baudrate, reason, profile, parameters = probe_sllidar(
                candidate,
                baudrates=lidar_baudrates,
            )
            if ok:
                results['lidar'] = DeviceResult(
                    role='lidar',
                    device=preferred_stable_path(candidate),
                    resolved_device=resolved,
                    baudrate=baudrate,
                    confidence='protocol_verified',
                    reason=reason,
                    protocol='sllidar_serial',
                    profile=profile,
                    parameters=parameters,
                )
                used_realpaths.add(resolved)
                break
            lidar_failures.append(f'{candidate}: {reason}')

        if require_lidar and 'lidar' not in results:
            details = '; '.join(lidar_failures) or 'no candidates'
            raise RuntimeError(f'SLLIDAR not detected. {details}')

    resolved_roles = [result.resolved_device for result in results.values()]
    if len(resolved_roles) != len(set(resolved_roles)):
        raise RuntimeError('One physical serial device was assigned more than once')

    _write_runtime(runtime_dir, results)
    return results
