"""HTTP adapter for settings owned by rover_navigation."""
from rover_navigation.runtime_settings import (
    DEFAULT_SETTINGS_FILE, RANGES, drive_type, load_settings, save_settings, validate,
)


class NavigationSettingsMixin:
    def init_navigation_settings(self):
        self.declare_parameter('navigation_settings_file', DEFAULT_SETTINGS_FILE)
        self.navigation_settings_file = str(self.get_parameter('navigation_settings_file').value)

    def navigation_settings_payload(self):
        with self._navigation_control_lock:
            busy = bool(self._navigation_process and self._navigation_process.poll() is None)
            external = self._node_is_visible('/slam_toolbox') or self._node_is_visible('/bt_navigator')
            return {
                'settings': load_settings(self.navigation_settings_file),
                'file': self.navigation_settings_file,
                'ranges': RANGES,
                'locked': busy or external,
                'drive_type': drive_type(self.drive_type_file),
            }

    def update_navigation_settings(self, payload):
        with self._navigation_control_lock:
            self._assert_navigation_runtime_idle()
            values = validate(payload)
            settings = {**load_settings(self.navigation_settings_file), **values}
            save_settings(settings, self.navigation_settings_file)
            return self.navigation_settings_payload()
