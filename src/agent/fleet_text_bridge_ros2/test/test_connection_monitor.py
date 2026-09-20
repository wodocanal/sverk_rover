import json
from types import SimpleNamespace
from unittest.mock import Mock

from fleet_text_bridge_ros2.connection_monitor import ConnectionMonitorMixin


def monitor():
    node = ConnectionMonitorMixin()
    node.robot_id = 'test-rover'
    node.declare_parameter = Mock()
    params = {'mqtt_host':'test.invalid','mqtt_port':1883,'connection_topic':'/fleet/connection'}
    node.get_parameter = lambda key: SimpleNamespace(value=params[key])
    node.create_publisher = Mock(return_value=Mock())
    node.create_timer = Mock()
    node.command_mqtt_topic = 'fleet/test/command'
    node.availability_mqtt_topic = 'fleet/test/availability'
    node._mqtt = Mock()
    node._mqtt.subscribe.return_value = (0, 12)
    node._mqtt.publish.return_value = SimpleNamespace(rc=0, mid=14)
    node._mqtt.is_connected.return_value = True
    node.init_connection_monitor()
    return node


def test_requires_connack_suback_and_puback_and_clears_on_reconnect():
    node = monitor()
    node._connection_started(node._mqtt, 0)
    assert node._connection['state'] == 'connecting'
    node._on_mqtt_subscribe(None, None, 12, [1])
    assert node._connection['state'] != 'connected'
    node._on_mqtt_publish(None, None, 14)
    assert node._connection['state'] == 'connected'
    node._publish_connection_status()
    payload = json.loads(node._connection_pub.publish.call_args.args[0].data)
    assert payload['connected'] and payload['availability_confirmed']
    assert payload['host'] == 'test.invalid' and payload['robot_id'] == 'test-rover'
    assert not any('password' in key or 'username' in key for key in payload)
    node._connection_started(node._mqtt, 0)
    assert not node._connection['subscribed']
    assert not node._connection['availability_confirmed']
    node._mqtt.is_connected.return_value = False
    node._publish_connection_status()
    assert not json.loads(node._connection_pub.publish.call_args.args[0].data)['connected']


def test_rejected_connection_subscription_and_publish_are_not_ready():
    node = monitor()
    node._connection_started(node._mqtt, 5)
    assert node._connection['state'] == 'error'
    node._mqtt.subscribe.assert_not_called()
    node._connection_started(node._mqtt, 0)
    node._on_mqtt_subscribe(None,None,12,[128])
    node._on_mqtt_publish(None,None,14)
    assert node._connection['state'] == 'error'
    node._mqtt.publish.return_value = SimpleNamespace(rc=4,mid=15)
    node._connection_started(node._mqtt,0)
    assert 'publish rc=4' in node._connection['error']
    node._on_mqtt_connect_fail(None,None)
    assert node._connection['state'] == 'disconnected'
