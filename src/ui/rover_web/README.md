# Rover Web

The working configuration is `config/web.yaml`. Launch standalone with:

```bash
ros2 launch rover_web web.launch.py
```

On the rover, `rover-web.service` owns the web UI independently of
`rover-bringup.service`.

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

The scan's +X axis points up and +Y points left; the marker points up. Points
are shown in the `LaserScan.header.frame_id` coordinate frame, as reported in
the source details. This is a local scan viewer, not a TF-transformed map view.

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
