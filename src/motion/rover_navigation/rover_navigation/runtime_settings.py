"""Persistent operator settings and package-owned launch parameter generation."""
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_package_share_directory
import yaml

DEFAULT_SETTINGS_FILE = '~/.config/sverk-rover/navigation.yaml'
DEFAULT_DRIVE_TYPE_FILE = '~/.config/sverk-rover/drive_type'
RANGES = {
    'resolution': (0.01, 0.20),
    'forward_speed': (0.05, 0.35),
    'reverse_speed': (0.05, 0.35),
    'lateral_speed': (0.05, 0.35),
    'angular_speed': (0.10, 1.50),
    'linear_acceleration': (0.05, 2.0),
    'linear_deceleration': (0.05, 3.0),
    'angular_acceleration': (0.10, 5.0),
    'angular_deceleration': (0.10, 6.0),
    'position_tolerance': (0.02, 0.50),
    'yaw_tolerance': (0.01, math.pi),
}
FLAGS = ('allow_reverse', 'allow_lateral')


def read_yaml(path):
    with Path(path).expanduser().open(encoding='utf-8') as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f'Expected YAML object: {path}')
    return value


def defaults():
    config = Path(get_package_share_directory('rover_navigation')) / 'config'
    nav = read_yaml(config / 'nav2.yaml')
    controller = nav['controller_server']['ros__parameters']
    dwb = controller['FollowPath']
    goal = controller['general_goal_checker']
    return dict(
        resolution=read_yaml(config / 'slam_toolbox.yaml')['slam_toolbox']['ros__parameters']['resolution'],
        allow_reverse=dwb['min_vel_x'] < 0,
        allow_lateral=dwb['max_vel_y'] > 0,
        forward_speed=dwb['max_vel_x'], reverse_speed=abs(dwb['min_vel_x']),
        lateral_speed=dwb['max_vel_y'], angular_speed=dwb['max_vel_theta'],
        linear_acceleration=dwb['acc_lim_x'], linear_deceleration=abs(dwb['decel_lim_x']),
        angular_acceleration=dwb['acc_lim_theta'], angular_deceleration=abs(dwb['decel_lim_theta']),
        position_tolerance=goal['xy_goal_tolerance'], yaw_tolerance=goal['yaw_goal_tolerance'],
    )


def validate(values):
    if not isinstance(values, dict) or set(values) - (set(RANGES) | set(FLAGS)):
        raise ValueError('Unknown navigation settings')
    result = dict(values)
    for key, value in values.items():
        if key in FLAGS:
            if not isinstance(value, bool):
                raise ValueError(f'{key}: expected boolean')
        else:
            low, high = RANGES[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key}: expected a number between {low} and {high}')
            result[key] = float(value)
    return result


def load_settings(filename=DEFAULT_SETTINGS_FILE):
    path = Path(filename).expanduser()
    return {**defaults(), **(validate(read_yaml(path)) if path.exists() else {})}


def save_settings(values, filename=DEFAULT_SETTINGS_FILE):
    values = validate(values)
    path = Path(filename).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.navigation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(values, stream, sort_keys=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def drive_type(filename=DEFAULT_DRIVE_TYPE_FILE):
    path = Path(filename).expanduser()
    value = path.read_text().strip() if path.exists() else 'mecanum'
    if value not in ('mecanum', 'differential'):
        raise ValueError('Invalid saved drive type')
    return value


def build_parameters(base, settings, mode, differential=False):
    """Modify a freshly loaded parameter tree, not the checked-in defaults."""
    s = settings
    if mode == 'slam':
        base['slam_toolbox']['ros__parameters']['resolution'] = s['resolution']
        return base
    ctrl = base['controller_server']['ros__parameters']
    dwb = ctrl['FollowPath']
    lateral = s['allow_lateral'] and not differential
    dwb.update(
        min_vel_x=-s['reverse_speed'] if s['allow_reverse'] else 0.0,
        max_vel_x=s['forward_speed'],
        min_vel_y=-s['lateral_speed'] if lateral else 0.0,
        max_vel_y=s['lateral_speed'] if lateral else 0.0,
        max_vel_theta=s['angular_speed'],
        max_speed_xy=max(s['forward_speed'], s['reverse_speed'] if s['allow_reverse'] else 0.0,
                         s['lateral_speed'] if lateral else 0.0),
        acc_lim_x=s['linear_acceleration'], acc_lim_y=s['linear_acceleration'],
        decel_lim_x=-s['linear_deceleration'], decel_lim_y=-s['linear_deceleration'],
        acc_lim_theta=s['angular_acceleration'], decel_lim_theta=-s['angular_deceleration'],
        vy_samples=dwb['vy_samples'] if lateral else 1,
        xy_goal_tolerance=s['position_tolerance'],
    )
    ctrl['general_goal_checker'].update(xy_goal_tolerance=s['position_tolerance'], yaw_goal_tolerance=s['yaw_tolerance'])
    base['amcl']['ros__parameters']['robot_model_type'] = (
        'nav2_amcl::DifferentialMotionModel' if differential else 'nav2_amcl::OmniMotionModel')
    behavior = base['behavior_server']['ros__parameters']
    behavior.update(max_rotational_vel=s['angular_speed'],
                    min_rotational_vel=min(0.1, s['angular_speed']),
                    rotational_acc_lim=s['angular_acceleration'])
    if not s['allow_reverse']:
        behavior['behavior_plugins'] = [name for name in behavior['behavior_plugins'] if name != 'backup']
        behavior.pop('backup', None)
    return base


def configure_launch(context, *, mode):
    """Generate private launch files; remove them when the launch shuts down."""
    from launch.actions import OpaqueFunction, RegisterEventHandler, SetLaunchConfiguration
    from launch.event_handlers import OnShutdown
    from launch.substitutions import LaunchConfiguration

    settings_path = LaunchConfiguration('settings_file').perform(context)
    settings = load_settings(settings_path)
    directory = tempfile.TemporaryDirectory(prefix='rover-navigation-')
    try:
        base = read_yaml(LaunchConfiguration('params_file').perform(context))
        # No override file means an explicit CLI params_file remains authoritative.
        if Path(settings_path).expanduser().exists():
            base = build_parameters(base, settings, mode,
                drive_type(LaunchConfiguration('drive_type_file').perform(context)) == 'differential')
        elif mode == 'navigation' and drive_type(LaunchConfiguration('drive_type_file').perform(context)) == 'differential':
            ctrl = base['controller_server']['ros__parameters']['FollowPath']
            ctrl.update(min_vel_y=0.0, max_vel_y=0.0, vy_samples=1)
            base['amcl']['ros__parameters']['robot_model_type'] = 'nav2_amcl::DifferentialMotionModel'
        if mode == 'navigation':
            ctrl = base['controller_server']['ros__parameters']['FollowPath']
            reverse_allowed = ctrl['min_vel_x'] < 0
            trees = Path(get_package_share_directory('nav2_bt_navigator')) / 'behavior_trees'
            navigator = base['bt_navigator']['ros__parameters']
            for key, source in (
                ('default_nav_to_pose_bt_xml', 'navigate_to_pose_w_replanning_and_recovery.xml'),
                ('default_nav_through_poses_bt_xml', 'navigate_through_poses_w_replanning_and_recovery.xml'),
            ):
                tree = ET.parse(navigator.get(key) or str(trees / source))
                for parent in tree.iter():
                    for child in list(parent):
                        if child.tag == 'BackUp':
                            if not reverse_allowed:
                                parent.remove(child)
                            else:
                                child.set('backup_speed', str(min(abs(ctrl['min_vel_x']), 0.15)))
                target = Path(directory.name) / source
                tree.write(target, encoding='unicode')
                navigator[key] = str(target)
        output = Path(directory.name) / 'params.yaml'
        output.write_text(yaml.safe_dump(base, sort_keys=False), encoding='utf-8')
    except Exception:
        directory.cleanup()
        raise

    def cleanup(_context):
        directory.cleanup()
        return []
    return [SetLaunchConfiguration('params_file', str(output)),
            RegisterEventHandler(OnShutdown(on_shutdown=[OpaqueFunction(function=cleanup)]))]
