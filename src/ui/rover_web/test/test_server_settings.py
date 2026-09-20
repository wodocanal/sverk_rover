import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fleet_text_bridge_ros2.runtime_settings import load_overrides
from rover_web.server_settings import ServerSettingsMixin


def gateway(tmp_path, monkeypatch):
    node = ServerSettingsMixin()
    node.fleet_settings_file = str(tmp_path / 'connection.json')
    node.fleet_bridge_node_name = '/fleet_text_bridge'
    node._server_settings_lock = threading.RLock()
    defaults = dict(mqtt_host='localhost', mqtt_port=1883, mqtt_topic_prefix='test', mqtt_username='')
    monkeypatch.setattr('rover_web.server_settings.package_defaults', lambda: defaults)
    node._bridge_settings = Mock(return_value=None)
    node.fleet_connection_state = Mock(return_value={'ready':False})
    node.record_activity = Mock()
    node._ensure_service_client = Mock()
    return node, defaults


def test_password_keep_replace_clear_and_offline_save(tmp_path, monkeypatch):
    node, values = gateway(tmp_path, monkeypatch)
    result = node.update_server_settings({'settings':{**values,'mqtt_password':'private'},'reconnect':True})
    assert not result['reconnect']['started']
    assert 'private' not in json.dumps(result)
    assert result['password_source'] == 'saved'
    assert load_overrides(node.fleet_settings_file)['mqtt_password'] == 'private'
    node.update_server_settings({'settings':{**values,'mqtt_password':''}})
    assert load_overrides(node.fleet_settings_file)['mqtt_password'] == 'private'
    result = node.update_server_settings({'settings':values,'clear_password':True})
    assert result['password_source'] == 'empty'
    assert load_overrides(node.fleet_settings_file)['mqtt_password'] == ''
    assert 'private' not in str(node.record_activity.call_args_list)


def test_reconnect_response_and_path_mismatch(tmp_path, monkeypatch):
    node, values = gateway(tmp_path, monkeypatch)
    current = dict(values, robot_id='test', connection_settings_file=node.fleet_settings_file)
    node._bridge_settings.return_value = current
    node._wait_for_future = Mock(return_value=SimpleNamespace(success=True, message='Started'))
    result = node.update_server_settings({'settings':values,'reconnect':True})
    assert result['reconnect']['started']
    node._ensure_service_client.assert_called_with('/fleet_text_bridge/reconnect', 'std_srvs/srv/Trigger')
    node._wait_for_future.return_value = SimpleNamespace(success=False, message='Busy')
    result = node.update_server_settings({'settings':values,'reconnect':True})
    assert result['reconnect'] == {'started':False,'message':'Busy'}
    node._ensure_service_client.reset_mock()
    current['connection_settings_file'] = '/different/path.json'
    result = node.update_server_settings({'settings':values,'reconnect':True})
    assert not result['can_reconnect']
    assert not result['reconnect']['started']
    node._ensure_service_client.assert_not_called()


def test_bad_request_does_not_write(tmp_path, monkeypatch):
    node, values = gateway(tmp_path, monkeypatch)
    for payload in [[], {}, {'settings':values,'reconnect':'yes'},
                    {'settings':{**values,'mqtt_password':'x'},'clear_password':True}]:
        with pytest.raises(ValueError):
            node.update_server_settings(payload)
    assert load_overrides(node.fleet_settings_file) == {}
