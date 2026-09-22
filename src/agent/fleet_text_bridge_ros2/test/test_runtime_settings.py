import stat

import pytest

from fleet_text_bridge_ros2.runtime_settings import load_overrides, save_overrides, validate


def test_private_persistence(tmp_path):
    path = tmp_path / 'private' / 'connection.json'
    assert load_overrides(path) == {}
    settings = dict(mqtt_host='127.0.0.1', mqtt_port=1883, mqtt_topic_prefix='fleet/test/',
                    mqtt_username='test', mqtt_password='test-secret')
    save_overrides(settings, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_overrides(path) == {**settings, 'mqtt_topic_prefix':'fleet/test'}
    save_overrides({**settings, 'mqtt_port':1884}, path)
    assert load_overrides(path)['mqtt_port'] == 1884
    assert len(list(path.parent.iterdir())) == 1
    path.write_text('{"mqtt_password": "hidden", "broken": 1}')
    with pytest.raises(ValueError, match='Invalid MQTT settings file') as error:
        load_overrides(path)
    assert 'hidden' not in str(error.value)


@pytest.mark.parametrize('values', [[], {'robot_id':'other'}, {'mqtt_port':True}, {'mqtt_port':0},
    {'mqtt_port':65536}, {'mqtt_host':'http://bad'}, {'mqtt_host':''}, {'mqtt_host':'bad host'},
    {'mqtt_topic_prefix':'fleet/+'}, {'mqtt_topic_prefix':'#'}, {'mqtt_username':'a\nb'},
    {'mqtt_password':123}])
def test_validation(values):
    with pytest.raises(ValueError):
        validate(values)
