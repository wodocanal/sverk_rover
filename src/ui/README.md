# UI packages

This folder groups ROS packages that provide user interfaces for the rover.
The folder itself is not a ROS package; colcon discovers the packages below it recursively.

Packages:

- `rover_web` - main browser-based rover control and diagnostics UI.
- `rover_display` - touchscreen application running on the Raspberry Pi display.
- `rosboard` - bundled ROSBoard web UI used as an additional ROS visualization tool.

In the default systemd deployment rover-web owns web/ttyd/rosboard, while the
physical display remains in rover-bringup (full profile). Web-started SLAM/Nav2
are also children of rover-web. See [service lifecycle](../../docs/operations.md).
