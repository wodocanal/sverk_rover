# Rover ROS 2 Workspace

ROS 2 workspace for the mecanum rover. The project contains hardware drivers,
robot description, wheel odometry, localization, navigation, web UI, display UI
and the text agent/server bridge.

## Repository Layout

```text
src/
├── agent/        # text agent, MCP server and MQTT fleet bridge
├── motion/       # wheel odometry, localization config and navigation/maps
├── peripherals/  # hardware drivers: base, lidar, IMU, camera, LEDs, audio
├── system/       # bringup, interfaces, description and vision
└── ui/           # web UI, display UI and rosboard
```

The main runtime configuration is centralized in:

```text
src/system/rover_bringup/config/
├── components/    # per-component runtime params
├── localization/  # EKF params used by bringup
├── navigation/    # Nav2 and SLAM params used by bringup
├── profiles/      # launch presets: full, agent, hardware, mapping, navigation, minimal
├── rover_v1.yaml  # robot identity, geometry and calibration
└── topics.yaml    # shared topics and TF frame names
```

Package-level `config/*.default.example.yaml` files are examples only. For the
real rover, prefer changing files under `rover_bringup/config`.

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
rosboard, `twist_mux`, local agent and MQTT fleet bridge.

Any component can be overridden from the command line:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full use_camera:=false
ros2 launch rover_bringup robot.launch.py profile:=full use_agent:=false
ros2 launch rover_bringup robot.launch.py profile:=full use_fleet_bridge:=false
ros2 launch rover_bringup robot.launch.py profile:=navigation use_nav2:=false
```

## Systemd Autostart

The rover can run the main bringup as a Linux service. Install it on the rover
after the workspace has been built:

```bash
cd ~/sverk_rover
deploy/systemd/install.sh
```

The installer creates:

```text
/etc/systemd/system/rover-bringup.service
/etc/default/rover-bringup
```

Edit `/etc/default/rover-bringup` to choose the launch profile and overrides:

```bash
sudo nano /etc/default/rover-bringup
```

Common settings:

```bash
ROVER_PROFILE=full
ROVER_DISCOVERY_MODE=configured
ROVER_LAUNCH_ARGS="use_camera:=false use_agent:=false"
```

Control the rover stack with:

```bash
sudo systemctl start rover-bringup
sudo systemctl stop rover-bringup
sudo systemctl restart rover-bringup
systemctl status rover-bringup
journalctl -u rover-bringup -f
```

Enable or disable autostart on boot:

```bash
sudo systemctl enable rover-bringup
sudo systemctl disable rover-bringup
```

## Web UI And Agent

The web UI starts from the `full` profile and listens on port `8765` by default.
Its config is:

```text
src/system/rover_bringup/config/components/web.yaml
```

The local MCP/LLM agent and MQTT fleet bridge are configured here:

```text
src/system/rover_bringup/config/components/agent.yaml
```

The agent MCP server uses port `8766` so it does not conflict with the web UI.
If the MQTT broker is not running on the rover itself, set `mqtt_host` in
`components/agent.yaml` to the server address.

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
