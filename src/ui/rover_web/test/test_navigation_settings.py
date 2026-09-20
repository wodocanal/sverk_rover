import threading
from unittest.mock import Mock

import pytest
from rover_web.navigation_settings import NavigationSettingsMixin


def test_save_reload_and_runtime_lock(tmp_path):
    node = NavigationSettingsMixin()
    node._navigation_control_lock = threading.RLock()
    node.navigation_settings_file = str(tmp_path/'navigation.yaml')
    node.drive_type_file = str(tmp_path/'drive_type')
    node._navigation_process = None
    node._node_is_visible = Mock(return_value=False)
    node._assert_navigation_runtime_idle = Mock()
    result = node.update_navigation_settings({'allow_reverse':False,'resolution':0.04})
    assert result['settings']['allow_reverse'] is False
    assert node.navigation_settings_payload()['settings']['resolution'] == 0.04
    node._assert_navigation_runtime_idle.side_effect = RuntimeError('running')
    with pytest.raises(RuntimeError): node.update_navigation_settings({'resolution':0.02})
    assert node.navigation_settings_payload()['settings']['resolution'] == 0.04
    node._node_is_visible.return_value = True
    assert node.navigation_settings_payload()['locked']


def test_web_always_saves_posegraph():
    import inspect
    from rover_web.web_gateway_node import RoverWebGateway
    assert '--occupancy-only' not in inspect.getsource(RoverWebGateway.save_mapping)
