#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

from ament_index_python.packages import (
    get_package_share_directory,
    get_packages_with_prefixes,
)


WORKSPACE = Path(os.environ.get('ROVER_WS', '/workspace')).resolve()
INSTALL_ROOT = (WORKSPACE / 'install').resolve()
COMMAND_TIMEOUT_SEC = 30.0
STARTUP_TIMEOUT_SEC = 20.0


class SmokeFailure(RuntimeError):
    pass


def _print_command(command: list[str]) -> None:
    print(f"\n[smoke] $ {' '.join(command)}", flush=True)


def run(
    command: list[str],
    timeout: float = COMMAND_TIMEOUT_SEC,
    show_output: bool = False,
) -> str:
    _print_command(command)
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if completed.stdout and (show_output or completed.returncode != 0):
        print(completed.stdout.rstrip())
    if completed.returncode != 0:
        raise SmokeFailure(
            f'Command returned {completed.returncode}: {" ".join(command)}'
        )
    return completed.stdout


def workspace_launches() -> list[tuple[str, str]]:
    launches: list[tuple[str, str]] = []
    for package, prefix_text in sorted(get_packages_with_prefixes().items()):
        prefix = Path(prefix_text).resolve()
        if not prefix.is_relative_to(INSTALL_ROOT):
            continue
        launch_dir = Path(get_package_share_directory(package)) / 'launch'
        if not launch_dir.is_dir():
            continue
        for launch_file in sorted(launch_dir.glob('*.py')):
            launches.append((package, launch_file.name))
    return launches


class ManagedLaunch:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.output = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> 'ManagedLaunch':
        _print_command(self.command)
        self.process = subprocess.Popen(
            self.command,
            text=True,
            stdout=self.output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return self

    def wait_until(
        self,
        predicate: Callable[[], bool],
        description: str,
        timeout: float = STARTUP_TIMEOUT_SEC,
    ) -> None:
        assert self.process is not None
        deadline = time.monotonic() + timeout
        last_error = ''
        while time.monotonic() < deadline:
            return_code = self.process.poll()
            if return_code is not None:
                raise SmokeFailure(
                    f'Launch exited before {description} with code {return_code}:\n'
                    f'{self.read_output()}'
                )
            try:
                if predicate():
                    print(f'[smoke] ready: {description}')
                    return
            except (OSError, subprocess.SubprocessError, URLError) as exc:
                last_error = str(exc)
            time.sleep(0.4)
        suffix = f' Last error: {last_error}' if last_error else ''
        raise SmokeFailure(
            f'Timed out waiting for {description}.{suffix}\n{self.read_output()}'
        )

    def read_output(self) -> str:
        self.output.flush()
        self.output.seek(0)
        return self.output.read()

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGINT)
            try:
                self.process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3.0)
        output = self.read_output().rstrip()
        if output and exc_type is not None:
            print(output)
        self.output.close()


def node_exists(name: str) -> bool:
    completed = subprocess.run(
        ['ros2', 'node', 'list'],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5.0,
    )
    return completed.returncode == 0 and name in completed.stdout.splitlines()


def web_identity(port: int) -> dict:
    with urlopen(f'http://127.0.0.1:{port}/api/identity', timeout=2.0) as response:
        if response.status != 200:
            raise SmokeFailure(f'Web identity returned HTTP {response.status}')
        payload = json.loads(response.read().decode('utf-8'))
    if not isinstance(payload, dict) or not payload:
        raise SmokeFailure('Web identity response is empty or invalid')
    return payload


def main() -> int:
    if not (INSTALL_ROOT / 'setup.bash').is_file():
        raise SmokeFailure(
            f'{INSTALL_ROOT}/setup.bash is missing; run make ros-build first'
        )

    launches = workspace_launches()
    if not launches:
        raise SmokeFailure(f'No workspace launch files found below {INSTALL_ROOT}')
    print(f'[smoke] validating {len(launches)} installed launch files')
    for package, launch_file in launches:
        run(['ros2', 'launch', package, launch_file, '--show-args'])

    safe_layers = (
        ['ros2', 'launch', 'rover_bringup', 'core.launch.py', 'profile:=none'],
        ['ros2', 'launch', 'rover_bringup', 'ui.launch.py', 'profile:=none'],
        ['ros2', 'launch', 'rover_bringup', 'mode.launch.py', 'mode:=idle'],
        [
            'ros2', 'launch', 'rover_bringup', 'integrations.launch.py',
            'profile:=none',
        ],
    )
    for command in safe_layers:
        run(command, show_output=True)

    with ManagedLaunch([
        'ros2', 'launch', 'rover_description', 'description.launch.py',
    ]) as description:
        description.wait_until(
            lambda: node_exists('/robot_state_publisher'),
            'robot_state_publisher node',
        )

    web_port = 18765
    with ManagedLaunch([
        'ros2', 'launch', 'rover_bringup', 'ui.launch.py',
        'profile:=web',
        'use_rosboard:=false',
        'terminal_enabled:=false',
        'start_terminal:=false',
        f'web_port:={web_port}',
    ]) as web:
        identity: dict = {}

        def identity_available() -> bool:
            nonlocal identity
            identity = web_identity(web_port)
            return True

        web.wait_until(identity_available, 'rover web identity API')
        print(f'[smoke] web identity: {json.dumps(identity, ensure_ascii=False)}')

    print(
        f'\n[smoke] PASS: {len(launches)} launch contracts, '
        '4 safe layers, robot description and web API'
    )
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (SmokeFailure, subprocess.TimeoutExpired) as exc:
        print(f'\n[smoke] FAIL: {exc}')
        raise SystemExit(1)
