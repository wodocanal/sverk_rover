# Rover ROS 2 project v0.4.3

This version keeps the active map inside the project and provides one-command
bringup for mapping, navigation and map updating.

## Map layout

```text
src/rover_navigation/maps/
├── current/          # map used by default by Nav2
│   ├── map.yaml
│   ├── map.pgm       # or another image format
│   ├── map.posegraph # created by rover_map save
│   ├── map.data      # created by rover_map save
│   └── map_info.json
└── archive/          # previous current maps
```

`src/rover_navigation/maps/current` is authoritative. The map command also
synchronizes the installed package copy, so navigation can start immediately
without rebuilding. A future colcon build installs the same source map again.

## Build

```bash
cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source ~/ros2_ws/install/setup.bash
```

Run `ros2 run rover_device_manager setup_devices` once on a newly assembled
rover before normal launch.

## Create a new map

Terminal 1:

```bash
ros2 launch rover_bringup mapping.launch.py
```

Terminal 2, optional RViz:

```bash
ros2 launch rover_description display_slam.launch.py
```

Terminal 3, manual mecanum control:

```bash
ros2 run rover_teleop mecanum_keyboard
```

Save the finished map while SLAM is still running:

```bash
ros2 run rover_navigation rover_map save room
```

This saves the occupancy map and SLAM Toolbox pose graph, archives the previous
`current`, and activates the new map.

Useful map commands:

```bash
ros2 run rover_navigation rover_map status
ros2 run rover_navigation rover_map list
ros2 run rover_navigation rover_map use <archive_directory_name>
```

## Navigate on the current map

Do not run SLAM Toolbox at the same time as AMCL navigation.

Terminal 1:

```bash
ros2 launch rover_bringup navigation.launch.py
```

Terminal 2, optional RViz:

```bash
ros2 launch rover_description display_navigation.launch.py
```

In RViz set the initial pose with **2D Pose Estimate** before sending a goal.
The first Nav2 motor test must be performed with the wheels lifted.

## Continue updating the current map

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

Use the SLAM RViz separately if required:

```bash
ros2 launch rover_description display_slam.launch.py
```

After updating the map, save it again under a new label:

```bash
ros2 run rover_navigation rover_map save room_updated
```

## Lower-level launches

The separate launches remain available for diagnostics:

```bash
ros2 launch rover_bringup robot.launch.py
ros2 launch rover_navigation slam.launch.py
ros2 launch rover_navigation navigation.launch.py
ros2 launch rover_navigation update_map.launch.py
```
