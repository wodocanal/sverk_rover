# Rover Configuration Guide

Runtime configuration is decentralized. Each package owns its working YAML and
its standalone launch reads that YAML. Bringup orchestrates the existing rover
launch and retains the component switches and profiles, not driver settings.

## Ownership

Paths below are relative to `src/`.

| Component | Working configuration |
| --- | --- |
| Launch composition | `system/rover_bringup/config/profiles/*.yaml` |
| Separate UI composition | `system/rover_bringup/config/profiles/ui.yaml` |
| Robot identity and physical geometry | `system/rover_description/config/rover_v1.yaml` |
| Shared topic names and TF frames | `system/rover_interfaces/config/topics.yaml` |
| Motors, wiring order/signs, encoder scale, speed limits | `peripherals/rover_base_driver/config/base.yaml` |
| Command priorities (external twist_mux node) | `peripherals/rover_base_driver/config/twist_mux.yaml` |
| Odometry and calibration multipliers | `motion/rover_wheel_odometry/config/odometry.yaml` |
| EKF with/without IMU | `motion/rover_wheel_odometry/config/localization/*.yaml` |
| Nav2 | `motion/rover_navigation/config/nav2.yaml` |
| SLAM Toolbox | `motion/rover_navigation/config/slam_toolbox.yaml` |
| Device discovery policy | `peripherals/rover_device_manager/config/device_manager.yaml` |
| IMU | `peripherals/rover_imu/config/imu.yaml` |
| LiDAR and baud-rate probing | `peripherals/sllidar_ros2/config/lidar.yaml` |
| LiDAR footprint filter | `peripherals/rover_lidar_filter/config/default.yaml` |
| Camera (including 180-degree rotation) | `peripherals/rover_camera/config/camera.yaml` |
| Vision | `system/rover_vision/config/vision.yaml` |
| LEDs | `peripherals/rover_led_strip/config/led_strip.yaml` |
| Octoliner | `peripherals/rover_octoliner/config/octoliner.yaml` |
| Speech and audio | `peripherals/rover_waveshare_audio/config/audio.yaml` |
| Web and terminal | `ui/rover_web/config/web.yaml` |
| Touchscreen | `ui/rover_display/config/display.yaml` |
| Rosboard | `ui/rosboard/config/rosboard.yaml` |
| MCP server and text agent | `agent/rover_agent_mcp/config/agent.yaml` |
| MQTT fleet bridge | `agent/fleet_text_bridge_ros2/config/bridge.yaml` |

Hardware device identities from the setup wizard remain in
`~/.config/rover/devices.json`. Do not rerun the wizard just because code changed.
Secrets and systemd overrides remain in `/etc/default/rover-bringup` and
`/etc/default/rover-web`, outside Git.

## One Value, One Owner

A ROS node config usually uses the standard structure:

```yaml
usb_camera_node:
  ros__parameters:
    fps: 30.0
    rotate: 180
```

Shared values use explicit package references, for example:

```yaml
wheel_odometry_node:
  ros__parameters:
    wheel_radius_m: package://rover_description/config/rover_v1.yaml#geometry.wheel_radius_m
    encoder_lines: package://rover_base_driver/config/base.yaml#base_driver_node.ros__parameters.encoder_lines
```

The `#` suffix selects a YAML value and preserves its type (float, list, bool,
etc.). A package URI without a suffix selects a file/directory path. Launches
resolve these through the ROS package index; no absolute workstation paths are
stored. Missing files/keys and cyclic references cause an explicit error.

A YAML containing package references must be loaded through the package launch,
not passed directly to `ros2 run --ros-args --params-file`: ROS itself does not
implement this reference syntax. Plain ROS YAML files without references can
still be used directly.

Agent `@mcp.url` references are computed from the configured MCP port.
`@env.NAME` reads an environment variable. The same robot ID reference is used
by the agent and bridge. Do not replace one of them with a different robot ID.

## Precedence And Launches

1. Node implementation defaults.
2. The package's working YAML (or an explicitly selected `config_file`).
3. Explicit launch arguments and systemd launch/environment overrides.

This is the startup layer, not a universal final precedence rule. A component
may then load its own persistent overrides. In particular:

| Saved setting | File under the service user's home | Application |
| --- | --- | --- |
| Serial roles | `~/.config/rover/devices.json` | Read by discovery before hardware launch |
| Mecanum/differential | `~/.config/sverk-rover/drive_type` | Shared by base, odometry, web and navigation |
| Motor/encoder mapping | `~/.config/sverk-rover/motor_calibration.json` | Overrides the four YAML arrays at driver restart |
| Nav2/SLAM settings | `~/.config/sverk-rover/navigation.yaml` | Applied to a temporary YAML at the next stack launch |
| MQTT connection | `~/.config/sverk-rover/fleet_connection.json` | Overrides startup connection parameters; reconnect or restart bridge |

The MQTT file can contain a password and is written with mode 0600. Never
commit it. The web and its consumers must agree on the file path and user.
Camera/vision changes made through ROS parameter services are runtime changes;
edit their package YAML for next-start defaults. Browser-local visibility and
manual speed choices are not shared robot configuration.

`*.example.yaml` files are examples, not runtime fallbacks. The agent and bridge
standalone launches expose `config_file`, not every YAML field as an argument.
For model/prompt changes use agent.yaml or the environment described in the
[agent README](../../../agent/rover_agent_mcp/README.md). Check `--show-args`
before assuming that a particular launch accepts an override.

Bringup supplies integration values such as discovered serial devices, shared
topic/frame names, robot geometry and simulation time. These are not separate
copies of driver tuning parameters. Old, explicitly supplied external
`components_config_dir`, robot and UI config overrides are kept for compatibility;
they are not read by default. An old component directory must contain its complete
original set of component YAMLs.

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
ros2 launch rover_bringup robot.launch.py profile:=mapping use_camera:=false
ros2 launch rover_camera camera.launch.py
ros2 launch rover_camera camera.launch.py fps:=15.0 rotate:=0
ros2 launch rover_base_driver base.launch.py
ros2 launch rover_wheel_odometry odometry.launch.py
ros2 launch rover_imu imu.launch.py
ros2 launch rover_description description.launch.py
ros2 launch rover_web web.launch.py
ros2 launch rover_agent_mcp agent_mcp.launch.py
ros2 launch fleet_text_bridge_ros2 bridge.launch.py
```

Do not run a standalone hardware launch alongside bringup if both would own the
same device. The `full` profile leaves Nav2 and SLAM disabled so the web UI can
start exactly one of them on demand from **Movement -> Visualization**. The
dedicated `navigation` and `mapping` profiles and standalone launch entry points
remain available for diagnostics; do not run them together with a web-managed
navigation mode.

## Updating An Existing Rover

Before updating, preserve any rover-specific local edits from the old bringup
config directory. Transfer them into the owning files above, especially motor
order/signs, encoder scale, IMU axes, robot ID and the MQTT server address.
The old `components/`, `localization/` and `navigation/` directories in bringup
are no longer runtime defaults.

Build the entire workspace once after this migration so the new
`rover_configuration` package and moved config files are installed:

Preserve the existing install mode. The example below uses a regular install;
add `--symlink-install` only if this workspace already uses that mode. Do not
mix regular/symlink or isolated/merged artifacts during an ordinary update.

```bash
cd ~/sverk_rover
sudo systemctl stop rover-web
sudo systemctl stop rover-bringup
source /opt/ros/jazzy/setup.bash
colcon build
```

Only after a successful build:

```bash
./deploy/systemd/install.sh
sudo systemctl start rover-bringup rover-web
systemctl is-enabled rover-bringup rover-web
systemctl is-active rover-bringup rover-web
```

The installer keeps existing `/etc/default/rover-*` files and enables both
services. If those files contain explicit paths to removed configs, update the
paths first. A previously running service needs `restart`, not `start`, to
reload settings. Environment-only changes do not require a rebuild.

With a symlink install, editing an existing YAML takes effect on the next
restart. Adding/renaming files or changing package metadata requires a rebuild.
Old copies may remain in an existing `install/` directory, but no default
launch in the new code reads the removed bringup paths.

Systemd reads `/etc/default/rover-bringup`; the web additionally reads
`/etc/default/rover-web`. It does not source `.bashrc`. Match ROS_DOMAIN_ID and
RMW in diagnostic terminals explicitly. `full` includes camera/vision, but
vision processing starts disabled. The physical Tkinter display belongs to
bringup, not rover-web. SLAM/Nav2 started by web belong to the web service and
stop when it restarts. See the [operations guide](../../../../docs/operations.md).

Documents are served from `docs/`. The compatibility parameter
`hackathon_files_root` in rover_web now points at `~/sverk_rover/docs`; update
any explicit old-path overrides. Moving documentation does not change API names.

## Checks

After building and sourcing `install/setup.bash`:

```bash
python3 -m unittest discover -s src/system/rover_configuration/test -v
python3 -m unittest discover -s src/system/rover_bringup/test -v
```

The launch tests use actual ROS launch classes but stub serial discovery and
never execute hardware nodes. Real hardware still needs a smoke test on the rover.
