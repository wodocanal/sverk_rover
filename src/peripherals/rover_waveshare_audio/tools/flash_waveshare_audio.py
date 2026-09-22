#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


ESPRESSIF_USB_JTAG_VID = 0x303A
ESPRESSIF_USB_JTAG_PID = 0x1001

GENERATED_DIRS = (
    'build',
    'managed_components',
    '__pycache__',
)
GENERATED_GLOBS = (
    'sdkconfig.old',
    '**/__pycache__',
)

PLAUSIBLE_TOKENS = (
    'esp32',
    'esp32-s3',
    'usb jtag',
    'usb serial',
    'serial/jtag',
    'jtag/serial',
    'espressif',
    'waveshare',
    'usbmodem',
    'ttyacm',
)


class SerialPort(NamedTuple):
    device: str
    description: str = ''
    manufacturer: str = ''
    vid: int | None = None
    pid: int | None = None
    serial_number: str = ''
    hwid: str = ''


def default_firmware_dir() -> Path:
    return Path(__file__).resolve().parents[1] / 'firmware' / 'speech-stream-stt'


def format_usb_id(port: SerialPort) -> str:
    if port.vid is None or port.pid is None:
        return '-'
    return f'{port.vid:04x}:{port.pid:04x}'


def list_ports_with_pyserial() -> list[SerialPort]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []

    ports: list[SerialPort] = []
    for item in list_ports.comports():
        ports.append(SerialPort(
            device=item.device,
            description=item.description or '',
            manufacturer=item.manufacturer or '',
            vid=item.vid,
            pid=item.pid,
            serial_number=item.serial_number or '',
            hwid=item.hwid or '',
        ))
    return ports


def list_ports_fallback() -> list[SerialPort]:
    if sys.platform == 'darwin':
        patterns = ['/dev/cu.usbmodem*', '/dev/cu.usbserial*']
    elif sys.platform.startswith('linux'):
        by_id = sorted(glob.glob('/dev/serial/by-id/*'))
        patterns = by_id if by_id else ['/dev/ttyACM*', '/dev/ttyUSB*']
    elif sys.platform.startswith('win'):
        patterns = []
    else:
        patterns = []

    devices: list[str] = []
    for pattern in patterns:
        if '*' in pattern:
            devices.extend(glob.glob(pattern))
        else:
            devices.append(pattern)

    return [SerialPort(device=device) for device in sorted(set(devices))]


def list_serial_ports() -> list[SerialPort]:
    ports = list_ports_with_pyserial()
    return ports if ports else list_ports_fallback()


def is_strict_match(port: SerialPort) -> bool:
    return (
        port.vid == ESPRESSIF_USB_JTAG_VID
        and port.pid == ESPRESSIF_USB_JTAG_PID
    )


def is_plausible_match(port: SerialPort) -> bool:
    if is_strict_match(port):
        return True
    haystack = ' '.join((
        port.device,
        port.description,
        port.manufacturer,
        port.serial_number,
        port.hwid,
    )).lower()
    return any(token in haystack for token in PLAUSIBLE_TOKENS)


def print_ports(ports: list[SerialPort]) -> None:
    if not ports:
        print('No serial ports found.')
        return

    print('Serial ports:')
    for port in ports:
        marker = '*' if is_strict_match(port) else ' '
        details = ', '.join(
            value
            for value in (
                f'usb={format_usb_id(port)}',
                f'desc={port.description}' if port.description else '',
                f'mfg={port.manufacturer}' if port.manufacturer else '',
                f'hwid={port.hwid}' if port.hwid else '',
            )
            if value
        )
        print(f' {marker} {port.device}  {details}')
    print('* = Espressif USB Serial/JTAG 303a:1001')


def select_port(explicit_port: str, allow_any_single_port: bool) -> str:
    if explicit_port:
        return explicit_port

    ports = list_serial_ports()
    strict = [port for port in ports if is_strict_match(port)]
    if len(strict) == 1:
        return strict[0].device
    if len(strict) > 1:
        print_ports(ports)
        raise SystemExit(
            'More than one Espressif USB Serial/JTAG device was found. '
            'Pass the intended port with --port.'
        )

    plausible = [port for port in ports if is_plausible_match(port)]
    if len(plausible) == 1:
        print(
            'Warning: no exact 303a:1001 match was reported, '
            f'using plausible port {plausible[0].device}.'
        )
        return plausible[0].device

    if allow_any_single_port and len(ports) == 1:
        print(
            'Warning: using the only visible serial port without USB identity: '
            f'{ports[0].device}.'
        )
        return ports[0].device

    print_ports(ports)
    raise SystemExit(
        'Could not uniquely identify the Waveshare ESP32-S3-AUDIO-Board. '
        'Reconnect only that board or pass --port explicitly.'
    )


def idf_command(allow_missing: bool = False) -> list[str]:
    idf_py = shutil.which('idf.py')
    if idf_py:
        return [idf_py]

    idf_path = os.environ.get('IDF_PATH', '').strip()
    if idf_path:
        candidate = Path(idf_path) / 'tools' / 'idf.py'
        if candidate.is_file():
            return [sys.executable, str(candidate)]

    if allow_missing:
        return ['idf.py']

    raise SystemExit(
        'idf.py was not found. Run this from an ESP-IDF terminal, source '
        '~/esp/esp-idf/export.sh, or install ESP-IDF first.'
    )


def cleanup_generated_files(firmware_dir: Path) -> None:
    removed: list[Path] = []

    for name in GENERATED_DIRS:
        path = firmware_dir / name
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(path)
        elif path.is_file():
            path.unlink()
            removed.append(path)

    for pattern in GENERATED_GLOBS:
        for path in firmware_dir.glob(pattern):
            if not path.exists() or path in removed:
                continue
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(path)
            elif path.is_file():
                path.unlink()
                removed.append(path)

    if removed:
        print('Cleaned generated ESP-IDF files:')
        for path in removed:
            print(f'  {path.relative_to(firmware_dir)}')
    else:
        print('No generated ESP-IDF files to clean.')


def run_flash(args: argparse.Namespace) -> int:
    firmware_dir = Path(args.firmware_dir).expanduser().resolve()
    if not (firmware_dir / 'CMakeLists.txt').is_file():
        raise SystemExit(f'Firmware directory is invalid: {firmware_dir}')

    if args.clean_only:
        cleanup_generated_files(firmware_dir)
        return 0

    port = select_port(args.port, args.allow_any_single_port)
    command = idf_command(allow_missing=args.dry_run) + ['-p', port]
    if args.erase:
        command.append('erase-flash')
    command.append('flash')
    if args.monitor:
        command.append('monitor')

    print(f'Firmware: {firmware_dir}')
    print(f'Port:     {port}')
    print('Command:  ' + ' '.join(command))

    if args.dry_run:
        return 0

    return_code = subprocess.run(command, cwd=firmware_dir, check=False).returncode
    if return_code == 0 and args.clean:
        cleanup_generated_files(firmware_dir)
    elif return_code != 0:
        print(
            'Flash command failed; generated files were left in place for debugging.',
            file=sys.stderr,
        )
    return return_code


def str_to_bool(value: str) -> bool:
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Find and flash the Waveshare ESP32-S3 audio module.',
    )
    parser.add_argument(
        '-p',
        '--port',
        default=os.environ.get('PORT', ''),
        help='Serial port override, for example /dev/ttyACM0 or COM5.',
    )
    parser.add_argument(
        '--firmware-dir',
        default=str(default_firmware_dir()),
        help='Path to firmware/speech-stream-stt.',
    )
    parser.add_argument(
        '--allow-any-single-port',
        action='store_true',
        help='Use the only visible serial port if USB identity is unavailable.',
    )
    parser.add_argument(
        '--erase',
        action='store_true',
        help='Erase flash before flashing firmware.',
    )
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='Open idf.py monitor after flashing.',
    )
    parser.add_argument(
        '--clean',
        action=argparse.BooleanOptionalAction,
        default=str_to_bool(os.environ.get('CLEAN_AFTER_FLASH', '1')),
        help='Remove ESP-IDF generated build files after successful flashing.',
    )
    parser.add_argument(
        '--clean-only',
        action='store_true',
        help='Only remove generated ESP-IDF files, do not flash.',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List detected serial ports and exit.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the selected port and idf.py command without flashing.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list:
        print_ports(list_serial_ports())
        return 0
    return run_flash(args)


if __name__ == '__main__':
    raise SystemExit(main())
