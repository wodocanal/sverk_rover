"""Fixed allowlist of systemd units exposed to the operator UI."""
from pathlib import Path
import subprocess


UNITS = {'bringup': 'rover-bringup.service', 'web': 'rover-web.service'}


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
    result = subprocess.run(
        ['systemctl', '--no-ask-password', '--no-block', 'restart', UNITS['web']],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()
                           or 'Systemd rejected rover-web restart')
