import json

from rover_agent_mcp.runtime_settings import apply_agent_runtime_settings, load_agent_runtime_settings


def test_runtime_settings_override_provider_without_secret_parameter(tmp_path):
    path = tmp_path / 'agent.json'
    path.write_text(json.dumps({
        'base_url':'http://10.0.0.2:8080/v1', 'model':'qwen', 'api_key':'secret',
    }))
    params, environment = apply_agent_runtime_settings(
        {'llm_base_url':'old', 'llm_model':'old'}, str(path)
    )
    assert params['llm_base_url'] == 'http://10.0.0.2:8080/v1'
    assert params['llm_model'] == 'qwen'
    assert 'api_key' not in params
    assert environment == {'OPENAI_API_KEY':'secret'}


def test_invalid_runtime_settings_are_ignored(tmp_path):
    path = tmp_path / 'agent.json'
    path.write_text('{broken')
    assert load_agent_runtime_settings(str(path)) == {}
