"""Private, persistent MQTT connection overrides shared with the local web UI."""
import json
import os
from pathlib import Path
import tempfile

DEFAULT_SETTINGS_FILE = '~/.config/sverk-rover/fleet_connection.json'
PUBLIC_KEYS = ('mqtt_host', 'mqtt_port', 'mqtt_topic_prefix', 'mqtt_username')


def validate(values):
    if not isinstance(values, dict) or set(values) - set((*PUBLIC_KEYS, 'mqtt_password')):
        raise ValueError('Unknown MQTT connection settings')
    result = dict(values)
    for key, value in result.items():
        if key == 'mqtt_port':
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError('MQTT port must be between 1 and 65535')
            continue
        if not isinstance(value, str) or len(value) > 1024 or '\x00' in value:
            raise ValueError(f'Invalid {key}')
        if key != 'mqtt_password':
            result[key] = value = value.strip()
            if any(ord(char) < 32 for char in value):
                raise ValueError(f'Invalid {key}')
        if key == 'mqtt_host' and (not value or any(c.isspace() for c in value) or '/' in value):
            raise ValueError('Specify a hostname or IP without protocol or path')
        if key == 'mqtt_topic_prefix':
            result[key] = value = value.rstrip('/')
            if not value or '+' in value or '#' in value:
                raise ValueError('MQTT prefix must not be empty or contain wildcards')
    return result


def load_overrides(filename=DEFAULT_SETTINGS_FILE):
    path = Path(filename).expanduser()
    if not path.exists():
        return {}
    try:
        return validate(json.loads(path.read_text(encoding='utf-8')))
    except (ValueError, TypeError):
        raise ValueError('Invalid MQTT settings file') from None


def save_overrides(values, filename=DEFAULT_SETTINGS_FILE):
    values = validate(values)
    path = Path(filename).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.fleet-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def package_defaults():
    from rover_configuration import config_path, environment_overrides, read_config, resolve_runtime_references
    values = resolve_runtime_references(read_config(config_path('fleet_text_bridge_ros2', 'bridge.yaml'))['fleet_bridge'])
    values = environment_overrides(values, {
        'mqtt_host': ('FLEET_MQTT_HOST|FLEET_SERVER_IP', str),
        'mqtt_port': ('FLEET_MQTT_PORT', int),
        'mqtt_topic_prefix': ('FLEET_MQTT_TOPIC_PREFIX', str),
        'mqtt_username': ('FLEET_MQTT_USERNAME', str),
    })
    return validate({key: values[key] for key in PUBLIC_KEYS})
