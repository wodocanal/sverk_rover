# rover_lidar_filter

ROS 2 node that removes lidar returns located inside the rover chassis footprint.
The scan points are transformed into `base_link`, so the lidar's forward offset and
its yaw are handled through TF rather than by hard-coded angular masks.

Default topics:

- input: `/scan` (raw driver output)
- output: `/scan_filtered` (used by SLAM, Nav2, RViz and the rover agent)

The filtered samples keep their original array indices and are replaced with
positive infinity, preserving the `sensor_msgs/msg/LaserScan` geometry.

## Launch and configuration

```bash
ros2 launch rover_lidar_filter filter.launch.py
```

Working config: [config/default.yaml](config/default.yaml). Despite its name,
this is the actual runtime YAML, not an example. It sets footprint bounds,
padding, base_frame_id, TF timeout and fallback sensor pose. Keep these in sync
with robot geometry. The physical driver's raw `/scan` must already exist;
do not start a second filter if bringup is running one.

Check `ros2 topic hz /scan_filtered` and TF availability. Filtering chassis
returns is not collision avoidance and does not remove all sensor noise.
The web viewer's display-only 180-degree rotation does not change this ROS scan.
