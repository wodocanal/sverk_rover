# Rover Bringup Configuration

`rover_bringup` now owns composition, not node runtime parameters. Each
functional package keeps its executable, active parameter files and public
launch file together. Bringup only selects those package launch files and
connects them for one assembled rover.

## Layout

- `rover_v1.yaml`: identity, geometry and calibration of this physical rover.
- `topics.yaml`: shared topic and TF frame contract between packages.
- `implementations.yaml`: package, launch file and hardware/software variant
  selected for each component.
- `profiles/core/`: hardware, odometry, localization and command arbitration.
- `profiles/ui/`: web, touchscreen display and rosboard combinations.
- `profiles/integrations/`: local agent and fleet/server bridge combinations.
- `profiles/*.yaml`: backward-compatible whole-rover presets used only by
  `robot.launch.py`.
- `core/twist_mux.yaml`: integration policy for the third-party `twist_mux`
  package, which has no project-local package of its own.

Node parameters now live with their owners. Important examples are:

```text
rover_base_driver/config/base.yaml
rover_imu/config/yb_mra02_v1.yaml
sllidar_ros2/config/c1.yaml
rover_wheel_odometry/config/odometry.yaml
rover_wheel_odometry/config/localization/*.yaml
rover_navigation/config/nav2.yaml
rover_navigation/config/slam_toolbox.yaml
rover_web/config/web.yaml
rover_agent_mcp/config/agent.yaml
fleet_text_bridge_ros2/config/bridge.yaml
```

## Launch Layers

The layers can run and restart independently:

```bash
ros2 launch rover_bringup core.launch.py profile:=full
ros2 launch rover_bringup ui.launch.py profile:=full
ros2 launch rover_bringup mode.launch.py mode:=navigation
ros2 launch rover_bringup integrations.launch.py profile:=full
```

Switch navigation to mapping without restarting hardware or UI:

```bash
# Stop the current mode process, then start only the replacement mode.
ros2 launch rover_bringup mode.launch.py mode:=mapping
```

`mode:=idle`, `navigation`, `mapping` and `update_map` are supported. Nav2/AMCL
and SLAM are intentionally never included in the same mode process because both
own the `map -> odom` transform.

## Compatibility Launch

The old single entry point remains available and composes the same four layers:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
ros2 launch rover_bringup robot.launch.py profile:=minimal
ros2 launch rover_bringup robot.launch.py profile:=agent
ros2 launch rover_bringup robot.launch.py profile:=hardware
ros2 launch rover_bringup robot.launch.py profile:=navigation
ros2 launch rover_bringup robot.launch.py profile:=mapping
```

Legacy component overrides continue to work:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full use_camera:=false
ros2 launch rover_bringup robot.launch.py profile:=mapping use_slam:=false
```

## Precedence

Runtime values are resolved in this order:

1. Node defaults in source code.
2. The active YAML in the component package.
3. Assembly-specific geometry, calibration, identity, topics and frames passed
   by bringup.
4. Explicit launch arguments.

Package `*.default.example.yaml` files remain examples. Active YAML files are
the source of truth for node behavior; `rover_v1.yaml` is the source of truth
only for this rover's identity, geometry and calibration.

## First-Test Boundaries

`rover_interfaces` remains one shared interface package in this version. It can
be split into narrowly scoped `*_interfaces` packages during the later package
layout refactor without changing these launch-layer contracts.

`rover_device_manager` is a preflight library/CLI rather than a persistent node,
so `core.launch.py` calls its discovery API before including serial-driver
launch files. Its policy still lives in
`rover_device_manager/config/device_manager.yaml`.
