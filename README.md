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
├── simulation/   # Gazebo model, worlds and hardware-compatible adapters
├── system/       # bringup, interfaces, description and vision
└── ui/           # web UI, display UI and rosboard
```

Runtime configuration is decentralized: each package owns its active node
parameters and public launch file. `rover_bringup` owns only composition:

```text
src/system/rover_bringup/config/
├── profiles/              # whole-rover compatibility and per-layer presets
├── core/twist_mux.yaml    # third-party command arbitration policy
├── implementations.yaml   # selected package launch and variant per component
├── rover_v1.yaml          # robot identity, geometry and calibration
└── topics.yaml            # shared topics and TF frame names
```

For example, base parameters live in `rover_base_driver/config/base.yaml`, EKF
parameters in `rover_wheel_odometry/config/localization`, Nav2 and SLAM
parameters in `rover_navigation/config`, and web parameters in
`rover_web/config/web.yaml`. Package `*.default.example.yaml` files are examples,
not active rover configuration.

For setting up a new physical rover from a cloned image, see:

```text
docs/rover-image-clone-setup.md
```

## Build

### Local Docker checks

On macOS, Windows or Ubuntu with Docker Desktop/Engine running, the complete
ROS 2 Jazzy workspace can be built and checked without installing ROS on the
host and without connecting rover hardware:

```bash
make ros-check
```

The first run builds a development image for the host architecture
(`linux/arm64` on Apple Silicon), installs dependencies with `rosdep`, builds
all packages, runs `colcon test`, validates every installed launch file and
starts safe description/web smoke checks. The workspace source is bind-mounted,
while `build`, `install` and `log` are kept in named Docker volumes for fast
repeat runs.

For the normal edit-test cycle, rebuild the image only after changing a
`package.xml` or Docker setup. Ordinary source and launch changes only need:

```bash
make ros-build
make ros-test
make ros-smoke
```

Useful Docker commands:

```bash
make docker-build  # refresh the image and rosdep dependencies
make ros-shell     # interactive shell with ROS and the workspace sourced
make docker-down   # stop containers; keep build/install/log volumes
make help
```

The local environment uses ROS domain `77` and restricts discovery to the
container host, so it does not accidentally join a physical rover's ROS graph.
Both values can be overridden for a command if needed:

```bash
ROS_DOMAIN_ID=88 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET make ros-shell
```

These checks cover buildability, existing unit tests, launch construction,
robot description startup and the web identity API. Physical serial devices,
GPIO/SPI/I2C and real motor/sensor behavior still require rover hardware.

### Local Gazebo simulation

The Docker image also contains Gazebo Harmonic, `gz_ros2_control` and Nav2.
Start Docker Desktop first. Rebuild the image once after adding simulation
dependencies, then run the headless drive/sensor smoke-test:

```bash
make docker-build
make sim-test
```

It verifies mecanum movement in all three axes, wheel-joint feedback, production
wheel odometry, lidar, IMU and camera data. An additional integration check
starts SLAM and then Nav2 in separate containers, checks vision and the web API,
and verifies an actual navigation goal at `(0.5, 0.0)` on the bundled field:

```bash
make sim-test-modes
```

To keep the simulation running with
the web UI at <http://localhost:8765>:

```bash
SIM_WORLD=empty SIM_MODE=idle SIM_UI=web make sim-run
```

Use the scanned field and start Nav2 or SLAM instead:

```bash
SIM_WORLD=field SIM_MODE=navigation SIM_UI=web make sim-run
SIM_WORLD=field SIM_MODE=mapping SIM_UI=web make sim-run
```

Stop the foreground simulation with `Ctrl+C`. These commands use headless
Gazebo with software rendering on macOS; the browser is the user interface,
not a native Gazebo desktop window. All simulation nodes use `/clock`.

`world=field` is generated from the occupied cells in the authoritative ROS map
`rover_navigation/maps/current/map.yaml`. Regenerate it after replacing or
updating that map:

```bash
make sim-world
```

`SIM_MAP` and `SIM_FIELD_OUTPUT` may override the repository-relative input and
output paths. The simulator replaces motor serial I/O, wheel encoders, RPLidar,
Yahboom IMU and USB camera, and provides mock battery/LED APIs for the web UI.
The real `twist_mux`, lidar filter, wheel odometry, EKF, vision, Nav2/SLAM and web
packages continue to run unchanged. Hardware discovery and all serial/GPIO/SPI/
I2C drivers are deliberately disabled.

Simulator defaults (world, spawn position, sensor resolution and rates) live in
`src/simulation/rover_gazebo/config/simulation.yaml`. Geometry remains in
`rover_bringup/config/rover_v1.yaml`; the controller and ROS/Gazebo topic bridge
are in `rover_gazebo/config/controllers.yaml` and `bridge.yaml`. Vision starts
with detection disabled, just like on the rover; enable it from the web UI.

The mecanum rollers are approximated using directed wheel friction rather than
individual roller meshes. The current camera pose is also approximate until it
is measured from a newer CAD assembly. These two details and real-world sensor
noise still need validation on physical hardware.

### Physical rover

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

The recommended test architecture has four independently restartable layers:

```bash
ros2 launch rover_bringup core.launch.py profile:=full
ros2 launch rover_bringup ui.launch.py profile:=full
ros2 launch rover_bringup mode.launch.py mode:=navigation
ros2 launch rover_bringup integrations.launch.py profile:=full
```

To switch from navigation to mapping, stop the current `mode.launch.py` process
and start `mode:=mapping`; core hardware and UI do not need to restart.

The backward-compatible all-in-one launch is still available:

Full physical rover stack:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
```

Hardware-only bringup without UI extras:

```bash
ros2 launch rover_bringup hardware.launch.py
```

Minimal base, odometry, wheel-only localization and robot description:

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

The `full` compatibility profile composes core hardware, UI, navigation and
integrations. It enables the same components as before the split.

Any component can be overridden from the command line:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full use_camera:=false
ros2 launch rover_bringup robot.launch.py profile:=full use_agent:=false
ros2 launch rover_bringup robot.launch.py profile:=full use_fleet_bridge:=false
ros2 launch rover_bringup robot.launch.py profile:=navigation use_nav2:=false
```

Each package can also be launched directly for diagnostics. Serial packages
expect the aliases created by `rover_device_manager` unless an explicit device
argument is supplied:

```bash
ros2 launch rover_base_driver base.launch.py
ros2 launch rover_imu imu.launch.py serial_device:=/dev/ttyUSB1
ros2 launch sllidar_ros2 lidar.launch.py serial_port:=/dev/ttyUSB2
ros2 launch rover_camera camera.launch.py
ros2 launch rover_navigation navigation.launch.py
ros2 launch rover_agent_mcp agent_mcp.launch.py
ros2 launch fleet_text_bridge_ros2 bridge.launch.py
```

## Systemd Autostart

The rover can run the same layers as separate Linux services. Install them after
the workspace has been built:

```bash
cd ~/sverk_rover
deploy/systemd/install.sh
```

The installer creates:

```text
/etc/systemd/system/rover-bringup.service
/etc/systemd/system/rover-web.service
/etc/systemd/system/rover-mode.service
/etc/systemd/system/rover-integrations.service
/etc/default/rover-bringup
/etc/default/rover-web
/etc/default/rover-mode
/etc/default/rover-integrations
```

Service ownership is explicit:

```text
rover-bringup      core hardware, odometry, localization and twist_mux
rover-web          web UI, terminal, touchscreen selection and rosboard
rover-mode         idle, navigation, mapping or update_map
rover-integrations local MCP/text agent and MQTT fleet bridge
```

Edit the matching environment file to configure one layer:

```bash
sudo nano /etc/default/rover-bringup
sudo nano /etc/default/rover-web
sudo nano /etc/default/rover-mode
sudo nano /etc/default/rover-integrations
```

Common settings:

```bash
ROVER_CORE_PROFILE=full
ROVER_DISCOVERY_MODE=configured
ROVER_LAUNCH_ARGS="use_camera:=false use_led_strip:=false"
ROVER_WEB_BIND_ADDRESS=0.0.0.0
ROVER_WEB_PORT=8765
ROVER_WEB_USE_ROSBOARD=true
ROVER_MODE=navigation
ROVER_INTEGRATIONS_PROFILE=full
```

Control the rover stack with:

```bash
sudo systemctl start rover-bringup
sudo systemctl start rover-web
sudo systemctl start rover-mode
sudo systemctl start rover-integrations
sudo systemctl restart rover-mode
sudo systemctl restart rover-integrations
sudo systemctl stop rover-integrations
sudo systemctl stop rover-mode
sudo systemctl stop rover-web
sudo systemctl stop rover-bringup
systemctl status rover-bringup
journalctl -u rover-mode -f
```

To switch only the active motion stack, set `ROVER_MODE=mapping` or
`ROVER_MODE=navigation` in `/etc/default/rover-mode`, then run
`sudo systemctl restart rover-mode`. The other three services keep running.

The installer preserves existing `/etc/default/rover-*` files. On an upgraded
rover, verify that `ROVER_WEB_COMMAND_TOPIC=/cmd_vel_teleop` when the core
profile enables `twist_mux`; use `/cmd_vel` only for a core profile without the
multiplexer.

Enable or disable autostart on boot:

```bash
sudo systemctl enable rover-bringup
sudo systemctl enable rover-web
sudo systemctl enable rover-mode
sudo systemctl enable rover-integrations
sudo systemctl disable rover-integrations
sudo systemctl disable rover-mode
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

For the systemd launch, put these values and optional MQTT credentials in
`/etc/default/rover-integrations`, then restart `rover-integrations` only.

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
ros2 launch rover_bringup core.launch.py profile:=full
ros2 launch rover_bringup peripherals.launch.py
ros2 launch rover_bringup ui.launch.py profile:=full
ros2 launch rover_bringup mode.launch.py mode:=navigation
ros2 launch rover_bringup integrations.launch.py profile:=full
ros2 launch rover_base_driver base.launch.py
ros2 launch rover_imu imu.launch.py variant:=yb_mra02_v1
ros2 launch sllidar_ros2 lidar.launch.py variant:=c1
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
