"""Persistent OpenAI-compatible provider settings for the rover agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_SETTINGS_FILE = '~/.config/sverk-rover/agent_connection.json'
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _validate_url(value: object) -> str:
    url = str(value or '').strip().rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Provider URL must be an absolute http:// or https:// URL')
    return url


def validate_settings(value: object, *, require_key: bool = False) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError('settings must be an object')
    unknown = set(value) - {'base_url', 'model', 'api_key'}
    if unknown:
        raise ValueError(f'Unknown agent settings: {", ".join(sorted(unknown))}')
    result = {
        'base_url': _validate_url(value.get('base_url')),
        'model': str(value.get('model') or '').strip(),
        'api_key': str(value.get('api_key') or '').strip(),
    }
    if not result['model']:
        raise ValueError('Model name is required')
    if require_key and not result['api_key']:
        raise ValueError('API key is required')
    if len(result['base_url']) > 2048 or len(result['model']) > 256 or len(result['api_key']) > 4096:
        raise ValueError('Agent setting is too long')
    return result


def load_settings(path: str = DEFAULT_SETTINGS_FILE) -> dict[str, str]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {key: str(value.get(key) or '').strip() for key in ('base_url', 'model', 'api_key')}


def save_settings(settings: dict[str, str], path: str = DEFAULT_SETTINGS_FILE) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, target)
        target.chmod(0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


class AgentSettingsMixin:
    def init_agent_settings(self):
        self.declare_parameter('agent_settings_file', DEFAULT_SETTINGS_FILE)
        self.agent_settings_file = str(Path(
            self.get_parameter('agent_settings_file').value
        ).expanduser().resolve())
        self._agent_settings_lock = threading.RLock()

    def _agent_effective_settings(self, submitted=None, *, require_key=True):
        saved = load_settings(self.agent_settings_file)
        candidate = {
            'base_url': saved.get('base_url') or os.getenv('OPENAI_BASE_URL', ''),
            'model': saved.get('model') or os.getenv('OPENAI_MODEL', ''),
            'api_key': saved.get('api_key') or os.getenv('OPENAI_API_KEY', ''),
        }
        if isinstance(submitted, dict):
            for key in ('base_url', 'model'):
                if key in submitted:
                    candidate[key] = submitted[key]
            if str(submitted.get('api_key') or '').strip():
                candidate['api_key'] = submitted['api_key']
        return validate_settings(candidate, require_key=require_key)

    def agent_settings_payload(self):
        saved = load_settings(self.agent_settings_file)
        return {
            'settings': {
                'base_url': saved.get('base_url') or os.getenv('OPENAI_BASE_URL', ''),
                'model': saved.get('model') or os.getenv('OPENAI_MODEL', ''),
            },
            'api_key_configured': bool(saved.get('api_key') or os.getenv('OPENAI_API_KEY', '')),
            'api_key_source': 'saved' if saved.get('api_key') else 'environment',
            'file': self.agent_settings_file,
            'notice': 'Changes apply after restarting rover-bringup.',
        }

    def update_agent_settings(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'settings', 'clear_api_key'}:
            raise ValueError('Unknown agent settings request')
        if type(payload.get('clear_api_key', False)) is not bool:
            raise ValueError('clear_api_key must be boolean')
        with self._agent_settings_lock:
            saved = load_settings(self.agent_settings_file)
            incoming = payload.get('settings')
            if not isinstance(incoming, dict):
                raise ValueError('settings must be an object')
            values = {
                'base_url': incoming.get('base_url'),
                'model': incoming.get('model'),
                'api_key': incoming.get('api_key') or saved.get('api_key', ''),
            }
            if payload.get('clear_api_key'):
                values['api_key'] = ''
            validated = validate_settings(values)
            save_settings(validated, self.agent_settings_file)
            self.record_activity('agent', 'AI provider settings saved', {
                'base_url': validated['base_url'], 'model': validated['model'],
            })
            return self.agent_settings_payload()

    @staticmethod
    def _provider_json(settings, path, payload=None, timeout=15.0):
        request = Request(
            f"{settings['base_url']}/{path.lstrip('/')}",
            data=None if payload is None else json.dumps(payload).encode('utf-8'),
            method='GET' if payload is None else 'POST',
            headers={
                'Authorization': f"Bearer {settings['api_key']}",
                'Accept': 'application/json', 'Content-Type': 'application/json',
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise RuntimeError('AI provider response is too large')
                return json.loads(raw.decode('utf-8'))
        except HTTPError as exc:
            detail = exc.read(2048).decode('utf-8', errors='replace')
            raise RuntimeError(f'AI provider returned HTTP {exc.code}: {detail}') from exc
        except URLError as exc:
            raise RuntimeError(f'Cannot connect to AI provider: {exc.reason}') from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f'Invalid or timed out AI provider response: {exc}') from exc

    def agent_provider_models(self, payload):
        submitted = payload.get('settings') if isinstance(payload, dict) else None
        settings = self._agent_effective_settings(submitted)
        response = self._provider_json(settings, 'models', timeout=12.0)
        items = response.get('data', []) if isinstance(response, dict) else []
        models = sorted({str(item.get('id')) for item in items if isinstance(item, dict) and item.get('id')})
        return {'ok': True, 'models': models, 'count': len(models)}

    def agent_provider_check(self, payload):
        submitted = payload.get('settings') if isinstance(payload, dict) else None
        settings = self._agent_effective_settings(submitted)
        response = self._provider_json(settings, 'chat/completions', {
            'model': settings['model'],
            'messages': [{'role': 'user', 'content': 'Reply with OK.'}],
            'max_tokens': 8, 'temperature': 0,
        }, timeout=30.0)
        choices = response.get('choices', []) if isinstance(response, dict) else []
        if not choices:
            raise RuntimeError('AI provider returned no completion choices')
        content = choices[0].get('message', {}).get('content', '')
        return {'ok': True, 'model': settings['model'], 'reply': str(content).strip()[:500]}
