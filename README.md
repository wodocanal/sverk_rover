# Rover ROS 2 Workspace

ROS 2 workspace for the mecanum rover. The project contains hardware drivers,
robot description, wheel odometry, localization, navigation, web UI, display UI
and the text agent/server bridge.

## Repository Layout

Project documentation and reference PDFs are stored in `docs/`. The web
interface's document browser also reads this directory. Its existing parameter
name, `hackathon_files_root`, is retained for compatibility and now defaults to
`~/sverk_rover/docs`. Update any custom override of this path when upgrading.

```text
src/
├── agent/        # text agent, MCP server and MQTT fleet bridge
├── motion/       # wheel odometry, localization config and navigation/maps
├── peripherals/  # hardware drivers: base, lidar, IMU, camera, LEDs, audio
├── system/       # bringup, interfaces, description and vision
└── ui/           # web UI, display UI and rosboard
```

Runtime parameters live in the package that owns the component. Bringup only
selects which components to start:

```text
src/system/rover_bringup/config/
└── profiles/      # full, agent, hardware, mapping, navigation, minimal, ui
```

For example, camera settings are in `rover_camera/config/camera.yaml`, motor
settings in `rover_base_driver/config/base.yaml`, and Nav2 settings in
`rover_navigation/config/nav2.yaml`. Main and standalone launches read the same
package-owned files. `*.example.yaml` files are documentation, not runtime defaults.

Shared identity/geometry is in `rover_description/config/rover_v1.yaml`; shared
topic/frame names are in `rover_interfaces/config/topics.yaml`. The utility
package `rover_configuration` resolves explicit cross-package YAML references;
it does not contain robot parameters. See the complete ownership table and
migration instructions in [Configuration Guide](src/system/rover_bringup/config/README.md).

For setting up a new physical rover from a cloned image, see:

```text
docs/rover-image-clone-setup.md
```

## Build

From the workspace root on the rover:

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

If this repository is checked out as `~/ros2_ws/src/...`, build from the
workspace root instead:

```bash
cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Run device setup once on a newly assembled rover:

```bash
ros2 run rover_device_manager setup_devices
```

This creates the persistent serial-device configuration used by the main launch.

## Main Launches

Full physical rover stack:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
```

Hardware-only bringup without UI extras:

```bash
ros2 launch rover_bringup hardware.launch.py
```

Minimal base, odometry and robot description:

```bash
ros2 launch rover_bringup robot.launch.py profile:=minimal
```

AI agent, local MCP server and MQTT fleet bridge only:

```bash
ros2 launch rover_bringup robot.launch.py profile:=agent
```

Nav2 navigation with the current map:

```bash
ros2 launch rover_bringup robot.launch.py profile:=navigation
```

SLAM Toolbox mapping:

```bash
ros2 launch rover_bringup robot.launch.py profile:=mapping
```

The `full` profile currently enables the base driver, wheel odometry, robot
description, EKF localization, IMU, lidar, LED strip, web UI, display UI,
rosboard, `twist_mux`, local agent and MQTT fleet bridge. It deliberately does
not start SLAM Toolbox or Nav2: these stacks are started on demand from
**Movement -> Visualization** in the web interface. Mapping starts only after
**Start map recording** is pressed. Navigation requires a valid map, an initial
pose and a goal before **Start navigation** becomes available.

See [Web mapping and navigation](docs/web-navigation.md) for the operator guide,
service update instructions and integration tests.

See [Web hardware setup](docs/web-hardware-setup.md) for the motor calibration
wizard and Device Manager, available under Settings.

See [Web agent chat](docs/web-agent.md) for sending ROS agent commands and
viewing replies, status updates and errors on the **Agent** page.

Any component can be overridden from the command line:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full use_camera:=false
ros2 launch rover_bringup robot.launch.py profile:=full use_agent:=false
ros2 launch rover_bringup robot.launch.py profile:=full use_fleet_bridge:=false
ros2 launch rover_bringup robot.launch.py profile:=navigation use_nav2:=false
```

## Systemd Autostart

The rover can run from Linux services. `rover-bringup` starts the main ROS
stack without the web UI, and `rover-web` starts the web UI separately. Install
them on the rover after the workspace has been built:

```bash
cd ~/sverk_rover
deploy/systemd/install.sh
```

The installer creates:

```text
/etc/systemd/system/rover-bringup.service
/etc/systemd/system/rover-web.service
/etc/default/rover-bringup
/etc/default/rover-web
```

Edit `/etc/default/rover-bringup` to choose the main launch profile and
overrides:

```bash
sudo nano /etc/default/rover-bringup
```

Common settings:

```bash
ROVER_PROFILE=full
ROVER_DISCOVERY_MODE=configured
ROVER_LAUNCH_ARGS="use_camera:=false use_agent:=false"
```

Edit `/etc/default/rover-web` to choose web UI settings:

```bash
sudo nano /etc/default/rover-web
```

Common settings:

```bash
ROVER_WEB_BIND_ADDRESS=0.0.0.0
ROVER_WEB_PORT=8765
ROVER_WEB_USE_ROSBOARD=true
```

Control the rover stack with:

```bash
sudo systemctl start rover-bringup
sudo systemctl start rover-web
sudo systemctl stop rover-web
sudo systemctl stop rover-bringup
sudo systemctl restart rover-bringup
sudo systemctl restart rover-web
systemctl status rover-bringup
journalctl -u rover-web -f
journalctl -u rover-bringup -f
```

Enable or disable autostart on boot:

```bash
sudo systemctl enable rover-bringup
sudo systemctl enable rover-web
sudo systemctl disable rover-web
sudo systemctl disable rover-bringup
```

## Web UI And Agent

The web UI is managed by `rover-web.service` and listens on port `8765` by
default. `rosboard` is also owned by `rover-web.service` by default, so
browser-facing tools stay out of `rover-bringup`. The web config is:

```text
src/ui/rover_web/config/web.yaml
```

The local MCP/LLM agent and MQTT fleet bridge are configured here:

```text
src/agent/rover_agent_mcp/config/agent.yaml
src/agent/fleet_text_bridge_ros2/config/bridge.yaml
```

The agent MCP server uses port `8766` so it does not conflict with the web UI.
If the MQTT broker is not running on the rover itself, set `mqtt_host` in
`fleet_text_bridge_ros2/config/bridge.yaml` to the server address.

LLM credentials are still expected through environment variables, for example:

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL='...'
export OPENAI_BASE_URL='...'
```

## Maps

The active map lives inside the navigation package:

```text
src/motion/rover_navigation/maps/
├── current/          # map used by default by Nav2
│   ├── map.yaml
│   ├── map.pgm
│   ├── map.posegraph
│   ├── map.data
│   └── map_info.json
└── archive/          # previous maps
```

`src/motion/rover_navigation/maps/current` is the authoritative map directory.
The `rover_map` command also synchronizes the installed package copy, so
navigation can start immediately without rebuilding.

## Create A New Map

Terminal 1:

```bash
ros2 launch rover_bringup mapping.launch.py
```

Terminal 2, optional RViz:

```bash
ros2 launch rover_description display_slam.launch.py
```

Move the rover using the web UI, Nav2 tools, or another `/cmd_vel` publisher.
Save the finished map while SLAM is still running:

```bash
ros2 run rover_navigation rover_map save room
```

Useful map commands:

```bash
ros2 run rover_navigation rover_map status
ros2 run rover_navigation rover_map list
ros2 run rover_navigation rover_map use <archive_directory_name>
```

## Navigate On The Current Map

Do not run SLAM Toolbox and AMCL navigation at the same time.

Terminal 1:

```bash
ros2 launch rover_bringup navigation.launch.py
```

Terminal 2, optional RViz:

```bash
ros2 launch rover_description display_navigation.launch.py
```

## License

This project is licensed under the [MIT License](LICENSE).
Copyright (c) 2026 Sverk. Third-party components retain their own licenses and
copyright notices; see the license files in their respective directories.

In RViz set the initial pose with `2D Pose Estimate` before sending a goal. For
the first Nav2 motor test, lift the wheels off the ground.

## Continue Updating The Current Map

The current map must contain `map.posegraph` and `map.data`. These files are
created by `rover_map save`.

When the rover is placed at the original first pose of the map:

```bash
ros2 launch rover_bringup update_map.launch.py
```

When the rover starts at a known pose in the map:

```bash
ros2 launch rover_bringup update_map.launch.py \
  start_mode:=given \
  initial_x:=1.2 \
  initial_y:=0.5 \
  initial_yaw:=1.57
```

After updating the map, save it again under a new label:

```bash
ros2 run rover_navigation rover_map save room_updated
```

## Diagnostics

Lower-level launches remain available for debugging:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
ros2 launch rover_bringup peripherals.launch.py
ros2 launch rover_bringup ui.launch.py
ros2 launch rover_navigation slam.launch.py
ros2 launch rover_navigation navigation.launch.py
ros2 launch rover_navigation update_map.launch.py
```

RViz display helpers:

```bash
ros2 launch rover_description display_model.launch.py
ros2 launch rover_description display_lidar.launch.py
ros2 launch rover_description display_odom.launch.py
ros2 launch rover_description display_slam.launch.py
ros2 launch rover_description display_navigation.launch.py
```
