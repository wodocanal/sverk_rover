"""Fixed allowlist of systemd units exposed to the operator UI."""
from pathlib import Path
import os
import pwd
import shutil
import subprocess
import time


UNITS = {'bringup': 'rover-bringup.service', 'web': 'rover-web.service'}
_permission_cache = None


def control_command(unit, action):
    if (unit, action) not in {(UNITS['bringup'], 'start'), (UNITS['bringup'], 'stop'),
                              (UNITS['web'], 'restart')}:
        raise ValueError('Service action is not allowed')
    binary = shutil.which('systemctl')
    if binary is None:
        raise RuntimeError('Systemctl is unavailable')
    command = [str(Path(binary).resolve()), '--no-ask-password']
    if unit == UNITS['web']:
        command.append('--no-block')
    return [*command, action, unit]


def control_unit(unit, action):
    command = control_command(unit, action)
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**os.environ, 'LC_ALL': 'C'},
                            timeout=5 if unit == UNITS['web'] else 45)
    if result.returncode == 0:
        return
    error = (result.stderr or result.stdout).strip()
    # Retry only an authorization failure, never a service failure/timeout:
    # a restart must not execute twice after an ambiguous result.
    denied = any(marker in error.lower() for marker in (
        'interactive authentication required', 'authentication is required',
        'access denied', 'permission denied', 'not authorized'))
    if denied and shutil.which('sudo'):
        result = subprocess.run(['sudo', '-n', '--', *command], capture_output=True,
                                text=True, env={**os.environ, 'LC_ALL': 'C'},
                                timeout=5 if unit == UNITS['web'] else 45)
        if result.returncode == 0:
            return
        error = (result.stderr or result.stdout).strip()
        denied = any(marker in error.lower() for marker in (
            'password is required', 'not allowed', 'not in the sudoers',
            'permission denied', 'access denied', 'authentication',
            'no new privileges', 'nosuid', 'effective uid'))
    if denied:
        user = pwd.getpwuid(os.geteuid()).pw_name
        raise RuntimeError(
            f'Нет прав на управление сервисами у пользователя веба {user}. '
            'На ровере из папки проекта один раз выполните: '
            'sudo bash deploy/systemd/install-service-control.sh\n'
            'Пароль вводится в SSH-терминале, а не в браузере. '
            f'Системная ошибка: {error}')
    raise RuntimeError(error or f'Systemd rejected {action} {unit}')


def service_control_permissions():
    """Read-only preflight; polkit may still grant direct access when sudo does not."""
    global _permission_cache
    now = time.monotonic()
    if _permission_cache and now - _permission_cache[0] < 10:
        return dict(_permission_cache[1])
    result = dict(user=pwd.getpwuid(os.geteuid()).pw_name, sudo_ready=False,
                  supported=Path('/run/systemd/system').is_dir(),
                  setup_command='sudo bash deploy/systemd/install-service-control.sh')
    if result['supported'] and shutil.which('sudo'):
        try:
            result['sudo_ready'] = all(subprocess.run(
                ['sudo', '-n', '-l', '--', *control_command(unit, action)],
                capture_output=True, text=True, timeout=2).returncode == 0
                for unit, action in ((UNITS['bringup'], 'start'), (UNITS['bringup'], 'stop'),
                                     (UNITS['web'], 'restart')))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    result['root'] = os.geteuid() == 0
    _permission_cache = (now, result)
    return dict(result)


def service_status():
    supported = Path('/run/systemd/system').is_dir()
    result = {}
    for key, unit in UNITS.items():
        item = dict(unit=unit, available=False, active_state='unknown', sub_state='', error='')
        if not supported:
            item['error'] = 'Systemd недоступен: веб запущен без Linux-сервисов.'
        else:
            try:
                process = subprocess.run(
                    ['systemctl', 'show', unit, '--no-pager',
                     '--property=LoadState,ActiveState,SubState,MainPID'],
                    capture_output=True, text=True, timeout=3,
                )
                if process.returncode:
                    raise RuntimeError(process.stderr.strip() or 'systemctl show failed')
                data = dict(line.split('=', 1) for line in process.stdout.splitlines() if '=' in line)
                item.update(available=data.get('LoadState') == 'loaded',
                            active_state=data.get('ActiveState', 'unknown'),
                            sub_state=data.get('SubState', ''),
                            main_pid=int(data.get('MainPID') or 0))
                if not item['available']:
                    item['error'] = 'Сервис не установлен. Выполните deploy/systemd/install.sh на ровере.'
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                item['error'] = str(exc)
        result[key] = item
    try:
        managed_web = '/rover-web.service' in Path('/proc/self/cgroup').read_text()
    except OSError:
        managed_web = False
    result['web']['managed_current_process'] = managed_web
    return result


def restart_web_unit():
    # PID 1 owns the restart job, so killing this web process cannot cancel it.
    control_unit(UNITS['web'], 'restart')
