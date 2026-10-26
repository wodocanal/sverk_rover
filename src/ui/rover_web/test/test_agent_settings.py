import json
from unittest.mock import Mock

import pytest

from rover_web.agent_settings import AgentSettingsMixin, load_settings, save_settings, validate_settings


def test_settings_are_private_and_secret_is_not_returned(tmp_path):
    path = tmp_path / 'agent.json'
    save_settings({'base_url':'http://localhost:8092/v1','model':'qwen','api_key':'secret'}, str(path))
    assert load_settings(str(path))['api_key'] == 'secret'
    assert path.stat().st_mode & 0o777 == 0o600
    node = object.__new__(AgentSettingsMixin)
    node.agent_settings_file = str(path)
    payload = node.agent_settings_payload()
    assert payload['api_key_configured']
    assert 'api_key' not in payload['settings']
    assert 'secret' not in json.dumps(payload)


def test_validation_rejects_non_http_url():
    with pytest.raises(ValueError):
        validate_settings({'base_url':'file:///tmp/key','model':'x','api_key':'y'})


def test_models_are_sorted(tmp_path):
    node = object.__new__(AgentSettingsMixin)
    node.agent_settings_file = str(tmp_path / 'agent.json')
    node._provider_json = Mock(return_value={'data':[{'id':'z'},{'id':'a'},{'bad':1}]})
    models = node.agent_provider_models({'settings': {
        'base_url':'http://provider/v1','model':'a','api_key':'key',
    }})
    assert models == {'ok':True, 'models':['a','z'], 'count':2}
