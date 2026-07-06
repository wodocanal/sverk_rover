#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def run(command: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def require_root() -> None:
    if hasattr(os, 'geteuid') and os.geteuid() != 0:
        print('This command must run as root', file=sys.stderr)
        sys.exit(1)


def load_netplan_tree() -> dict:
    completed = run(['netplan', 'get'], timeout=10.0)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or 'netplan get failed')

    text = completed.stdout
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {}


def parse_netplan_text_fallback(text: str, interface: str) -> tuple[str, str]:
    iface_pattern = re.compile(rf'^\s+{re.escape(interface)}:\s*$')
    ap_pattern = re.compile(r'^\s+"?(.*?)"?\s*:\s*$')
    password_pattern = re.compile(r'^\s+password:\s+"?(.*?)"?\s*$')

    in_iface = False
    in_access_points = False
    ssid = ''
    password = ''

    for line in text.splitlines():
        if iface_pattern.match(line):
            in_iface = True
            in_access_points = False
            continue

        if in_iface and line.startswith('    ') and not line.startswith('      '):
            in_iface = False
            in_access_points = False

        if not in_iface:
            continue

        if line.strip() == 'access-points:':
            in_access_points = True
            continue

        if not in_access_points:
            continue

        if not ssid:
            match = ap_pattern.match(line)
            if match and match.group(1) not in {'auth', 'key-management', 'password'}:
                ssid = match.group(1)
                continue

        if ssid and not password:
            match = password_pattern.match(line)
            if match:
                password = match.group(1)
                break

    return ssid, password


def current_config(interface: str) -> int:
    require_root()
    ssid = ''
    password = ''

    try:
        data = load_netplan_tree()
        aps = (
            data.get('network', {})
            .get('wifis', {})
            .get(interface, {})
            .get('access-points', {})
        )
        if isinstance(aps, dict) and aps:
            ssid = str(next(iter(aps.keys())))
            ap_cfg = aps.get(ssid) or {}
            if isinstance(ap_cfg, dict):
                auth_cfg = ap_cfg.get('auth') or {}
                if isinstance(auth_cfg, dict):
                    password = str(auth_cfg.get('password') or '')
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not ssid:
        completed = run(['netplan', 'get'], timeout=10.0)
        if completed.returncode == 0:
            ssid, password = parse_netplan_text_fallback(completed.stdout, interface)

    print(f'SSID={ssid}')
    print(f'PASSWORD={password}')
    return 0


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def apply_config(interface: str, netplan_file: str, ssid: str, password: str) -> int:
    require_root()

    if not ssid:
        print('SSID must not be empty', file=sys.stderr)
        return 1
    if len(password) < 8:
        print('Wi-Fi password must be at least 8 characters', file=sys.stderr)
        return 1

    config_path = Path(netplan_file)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        'network:\n'
        '  version: 2\n'
        '  wifis:\n'
        f'    {interface}:\n'
        '      optional: true\n'
        '      dhcp4: true\n'
        '      access-points:\n'
        f'        {yaml_quote(ssid)}:\n'
        '          auth:\n'
        '            key-management: "psk"\n'
        f'            password: {yaml_quote(password)}\n'
    )
    config_path.write_text(content, encoding='utf-8')

    generated = run(['netplan', 'generate'], timeout=20.0)
    if generated.returncode != 0:
        print(generated.stderr.strip() or generated.stdout.strip() or 'netplan generate failed', file=sys.stderr)
        return 1

    applied = run(['netplan', 'apply'], timeout=30.0)
    if applied.returncode != 0:
        print(applied.stderr.strip() or applied.stdout.strip() or 'netplan apply failed', file=sys.stderr)
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)

    current = subparsers.add_parser('current')
    current.add_argument('interface')

    apply = subparsers.add_parser('apply')
    apply.add_argument('interface')
    apply.add_argument('netplan_file')
    apply.add_argument('ssid')
    apply.add_argument('password')

    args = parser.parse_args()
    if args.command == 'current':
        return current_config(args.interface)
    if args.command == 'apply':
        return apply_config(args.interface, args.netplan_file, args.ssid, args.password)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
