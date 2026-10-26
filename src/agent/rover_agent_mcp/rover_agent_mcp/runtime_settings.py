"""Load web-managed LLM settings without exposing the saved secret as a ROS parameter."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_AGENT_SETTINGS_FILE = '~/.config/sverk-rover/agent_connection.json'


def load_agent_runtime_settings(path: str | None = None) -> dict[str, str]:
    target = Path(path or os.getenv('AGENT_SETTINGS_FILE', DEFAULT_AGENT_SETTINGS_FILE)).expanduser()
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        key: str(value.get(key) or '').strip()
        for key in ('base_url', 'model', 'api_key')
        if str(value.get(key) or '').strip()
    }


def apply_agent_runtime_settings(parameters: dict, path: str | None = None):
    settings = load_agent_runtime_settings(path)
    updated = dict(parameters)
    if settings.get('base_url'):
        updated['llm_base_url'] = settings['base_url'].rstrip('/')
    if settings.get('model'):
        updated['llm_model'] = settings['model']
    environment = {'OPENAI_API_KEY': settings['api_key']} if settings.get('api_key') else {}
    return updated, environment
