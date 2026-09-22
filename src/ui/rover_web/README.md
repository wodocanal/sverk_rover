# Rover Web

The working configuration is `config/web.yaml`. Launch standalone with:

```bash
ros2 launch rover_web web.launch.py
```

On the rover, `rover-web.service` owns the web UI independently of
`rover-bringup.service`.

## Operator Features

The main page includes identity and systemd controls. Settings contains motor
calibration, Device Manager, drive type, map/navigation and MQTT settings.
The Agent page sends ROS messages and shows replies and commands received from
the server; it does not start the agent. The camera page controls the vision
pipeline, displays detections, and offers ArUco/QR switches.

- [Mapping, saved maps and navigation](../../../docs/web-navigation.md).
- [Named destinations and agent navigation](../../../docs/named-places.md).
- [Hardware setup and limited service permissions](../../../docs/web-hardware-setup.md).
- [Agent/server connection and persistent settings](../../../docs/web-agent.md).
- [Vision models and marker recognition](../../../docs/vision-markers.md).
- [Service ownership, updates and build modes](../../../docs/operations.md).

SLAM/Nav2 are child processes of the web gateway when launched from this UI.
Closing a browser does not stop them, but restarting rover-web does. Save the
map and stop movement first. No separate navigation systemd service exists.

The document browser reads `docs/` via the compatibility parameter
`hackathon_files_root`. Maps default to rover_navigation/maps/current and its
sibling archive. Manual speed/page-visibility preferences are browser-local;
drive type, calibration, navigation and MQTT have separate persistent files.
Camera/vision ROS parameter edits are not automatically saved into package YAML.

This is an operator interface for a trusted network, not an authenticated
public service. Do not expose the gateway, ttyd or rosboard directly to the
Internet. Limited systemd permissions do not add HTTP authentication.

## Peripheral Page Visibility

Settings provides separate checkboxes for servos, voice recognition and Octoliner.
These control only the UI, not ROS node lifecycle. Manual choices are stored in
the browser; "Вернуть автоматическую видимость" clears these overrides.

`voice_page_mode` and `octoliner_page_mode` in `config/web.yaml` accept `auto`,
`enabled` or `disabled`. In `auto` (default), the gateway checks the configured
`voice_node_name` and `octoliner_node_name` in the ROS graph. This works when
`rover-web` is a separate service; defaults refresh every 12 seconds and may
take time to reflect ROS discovery. A stopped/crashed node is considered absent.

When `robot.launch.py` includes the web UI, it passes the resolved
`waveshare_audio` and `octoliner` component flags from the selected profile,
including `use_waveshare_audio`/`use_octoliner` launch overrides. These represent
launch intent, not node health. A separately launched web service cannot infer
the active hardware profile from its own UI profile, so it uses ROS discovery
instead. Browser preferences always take priority over automatic defaults.

## Live Camera

The web camera view requests the latest snapshot from `/api/camera/frame`.
Only one request is in flight; the next starts after image decoding. Slow clients
skip intermediate frames instead of replaying a buffered MJPEG stream. Requests
time out after 1.5 seconds, hidden tabs pause fetching, and changing the source
aborts pending requests. Frames not updated for 2 seconds are rejected.
The legacy `/api/camera/stream` endpoint remains available for other clients;
it does not provide this browser-side backpressure protection.

Image subscriptions and the USB camera publishers use best-effort QoS with
depth 1. JPEG encoding runs outside the USB capture thread, so slow compression
does not stop reading new frames. This prioritizes freshness over frame rate;
network transfer, exposure, decoding and compression still add latency.

After updating the source, build `rover_camera` and `rover_web`, restart
`rover-bringup` and `rover-web`, and reload the browser. Stop robot motion before
restarting bringup. Verify latency with a moving object or a visible stopwatch.

## LiDAR Viewer

Open **Peripherals -> LiDAR** and select a `sensor_msgs/msg/LaserScan` topic.
The viewer prefers `/scan_filtered` when it is available. Changing the source
connects immediately; the Connect button also reconnects the current source.

- Wheel/trackpad scrolling over the canvas zooms around the cursor.
- Drag with the left mouse button or one finger to pan.
- Pinch with two fingers to zoom and pan on touchscreens.
- The plus/minus buttons zoom around the viewport center.
- Reset View or a double-click fits the latest points and centers the marker.
- With the canvas focused, use arrow keys to pan, plus/minus to zoom, and
  Home or 0 to reset.

Zoom is limited to 25%-3200%. New scans do not reset the chosen view. The initial
fit uses actual valid returns, not the maximum distance supported by the sensor.
The distance ruler is in meters.

The cloud is rotated 180 degrees in the viewer to match the mounted lidar:
the scan's -X axis points up and -Y points left; the rover marker still points up.
This display-only correction applies to both raw and filtered scans and does not
change ROS messages or TF. The source details report `LaserScan.header.frame_id`.
This is a local scan viewer, not a TF-transformed map view.

The web LaserScan subscription uses sensor-data QoS (`BEST_EFFORT`, `VOLATILE`),
which accepts both reliable raw scans and best-effort filtered scans. It does
not change the publishers or navigation subscriptions. Invalid/infinite ranges
are removed before limiting the visualization to 720 points; the valid-point
counter still reports all valid returns.

The status distinguishes a missing first message, a received scan with no
valid returns, stale data, and an HTTP/ROS error. Existing data remains visible
if a stream stops, with its age and stale status.

## Checks

Frontend viewport and gesture tests (Node.js, no extra dependencies):

```bash
node --test src/ui/rover_web/test/lidar-view.test.cjs
node --check src/ui/rover_web/web/assets/app.js
```

After a ROS 2 build and `source install/setup.bash`, from the workspace root:

```bash
colcon test --packages-select rover_web --return-code-on-test-failure
colcon test-result --verbose
```

The ROS tests publish synthetic LaserScan messages with both reliability
policies and verify the actual web subscription callbacks. No physical devices
or motion commands are used.

After updating on a rover, rebuild `rover_web` (the viewer adds a new JS asset),
restart `rover-web`, and reload the browser page:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select rover_web
sudo systemctl restart rover-web
```

The build example assumes this workspace already uses symlink install. For a
regular install omit that flag; never switch modes over existing artifacts.
