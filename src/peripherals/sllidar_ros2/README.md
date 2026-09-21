# sllidar_ros2

Bundled SLAMTEC ROS 2 driver and SDK, integrated into Sverk Rover.
The upstream [Slamtec driver](https://github.com/Slamtec/sllidar_ros2) and
[SDK](https://github.com/Slamtec/rplidar_sdk) retain their notices and
[license](LICENSE). The root MIT license does not replace these terms.

## Launch in this workspace

Use the existing ROS 2 Jazzy workspace; do not clone a second package with the
same name into src. Preserve the workspace's regular/symlink install mode.
Prepare the serial alias through rover_device_manager first, and stop any
other owner of the lidar port.

```bash
ros2 launch sllidar_ros2 sllidar_c1_launch.py
```

Working configuration: [config/lidar.yaml](config/lidar.yaml). Bringup can pass
baudrate/profile values discovered for the actual device. Serial baudrate and
scan mode must match the model; defaults are not a universal autodetector.
Ensure the service user has read/write access to the serial device through
appropriate device-group/udev policy, not blanket chmod 777.

## Data and visualization

The driver publishes raw `/scan` (sensor_msgs/LaserScan). The separate
[rover_lidar_filter](../rover_lidar_filter/README.md) produces `/scan_filtered`
for SLAM, Nav2 and other consumers. A physical lidar can spin without supplying
valid scans, so check messages and timestamps, not just the motor.

Optional driver plus RViz launch:

```bash
ros2 launch sllidar_ros2 view_sllidar_c1_launch.py
```

It must not duplicate a driver already running in bringup. Upstream launch
variants for A1/A2/A3/S-series/T-series are not all included here; use only the
files in [launch](launch) and verify model parameters before deployment.
Correct lidar_link TF comes from rover_description. The web-only cloud rotation
does not alter the ROS frame or calibrate mounting.
