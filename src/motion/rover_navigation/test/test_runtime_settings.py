import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext
import yaml

from rover_navigation.runtime_settings import (
    build_parameters, configure_launch, defaults, load_settings, read_yaml, save_settings, validate,
)


def test_settings_validation_and_persistence(tmp_path):
    path = tmp_path/'settings.yaml'
    original = load_settings(path)
    assert original['resolution'] == 0.05
    save_settings({**original, 'resolution':0.03, 'allow_reverse':False}, path)
    assert load_settings(path)['resolution'] == 0.03
    for values in [{'resolution':0}, {'forward_speed':float('nan')}, {'allow_reverse':'false'},
                   {'angular_speed':True}, {'unknown':1}, {'forward_speed':2}]:
        with pytest.raises(ValueError): validate(values)


def test_dwb_restrictions_speeds_tolerances_and_differential():
    base = read_yaml(Path(get_package_share_directory('rover_navigation'))/'config/nav2.yaml')
    settings = {**defaults(), 'allow_reverse':False, 'allow_lateral':False,
                'forward_speed':0.12, 'angular_speed':0.3, 'position_tolerance':0.15}
    result = build_parameters(copy.deepcopy(base), settings, 'navigation')
    dwb = result['controller_server']['ros__parameters']['FollowPath']
    assert dwb['min_vel_x'] == dwb['min_vel_y'] == dwb['max_vel_y'] == 0.0
    assert dwb['max_vel_x'] == dwb['max_speed_xy'] == 0.12
    assert dwb['max_vel_theta'] == 0.3
    assert dwb['xy_goal_tolerance'] == 0.15
    assert 'backup' not in result['behavior_server']['ros__parameters']['behavior_plugins']
    settings['allow_lateral'] = True
    result = build_parameters(copy.deepcopy(base), settings, 'navigation', differential=True)
    assert result['controller_server']['ros__parameters']['FollowPath']['max_vel_y'] == 0.0
    assert 'Differential' in result['amcl']['ros__parameters']['robot_model_type']


@pytest.mark.parametrize('mode', ['slam', 'navigation'])
def test_launch_generates_effective_parameters_and_safe_trees(tmp_path, mode):
    settings_file = tmp_path/'settings.yaml'
    save_settings({**defaults(), 'resolution':0.03, 'allow_reverse':False}, settings_file)
    config = Path(get_package_share_directory('rover_navigation'))/'config'
    context = LaunchContext()
    context.launch_configurations.update(settings_file=str(settings_file),
        drive_type_file=str(tmp_path/'drive_type'),
        params_file=str(config/('slam_toolbox.yaml' if mode=='slam' else 'nav2.yaml')))
    actions = configure_launch(context, mode=mode)
    actions[0].execute(context)
    path = Path(context.launch_configurations['params_file'])
    generated = read_yaml(path)
    if mode == 'slam':
        assert generated['slam_toolbox']['ros__parameters']['resolution'] == 0.03
    else:
        assert generated['controller_server']['ros__parameters']['FollowPath']['min_vel_x'] == 0.0
        for key in ['default_nav_to_pose_bt_xml','default_nav_through_poses_bt_xml']:
            tree = ET.parse(generated['bt_navigator']['ros__parameters'][key])
            assert not list(tree.iter('BackUp'))
            assert list(tree.iter('Spin'))


def test_saved_limits_also_limit_backup_tree(tmp_path):
    path = tmp_path/'settings.yaml'
    save_settings({**defaults(), 'reverse_speed':0.06}, path)
    context = LaunchContext()
    context.launch_configurations.update(settings_file=str(path), drive_type_file=str(tmp_path/'drive'),
        params_file=str(Path(get_package_share_directory('rover_navigation'))/'config/nav2.yaml'))
    actions = configure_launch(context, mode='navigation')
    actions[0].execute(context)
    params = read_yaml(context.launch_configurations['params_file'])
    tree = ET.parse(params['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml'])
    assert [node.attrib['backup_speed'] for node in tree.iter('BackUp')] == ['0.06']
