# Rover Image Clone Setup

This guide describes what must be changed after copying one rover image to a
new physical rover so several rovers can run at the same time and communicate
with one server.

The short version: every rover needs a unique robot identity, Linux hostname,
ROS domain, and physical device setup. Server address and common software
configuration can usually stay the same.

## Example Fleet Values

Use a simple numbered scheme:

```text
rover-01  SVR-0001  ROS_DOMAIN_ID=1
rover-02  SVR-0002  ROS_DOMAIN_ID=2
rover-03  SVR-0003  ROS_DOMAIN_ID=3
```

Avoid reusing `robot.id`. The server and rover fleet bridge use this as the
robot identity.

## 1. Stop Rover Services

Before changing identity or serial-device setup, stop the running rover stack:

```bash
sudo systemctl stop rover-bringup
```

If the service is not installed yet, this command can fail harmlessly.

## 2. Change Linux Hostname

Set a unique hostname for this physical rover:

```bash
sudo hostnamectl set-hostname rover-02
```

Update `/etc/hosts`:

```bash
sudo nano /etc/hosts
```

Replace the old rover name with the new one. A typical line should look like:

```text
127.0.1.1 rover-02
```

Check:

```bash
hostnamectl
hostname
```

## 3. Change Rover Identity

Edit the main robot config:

```bash
nano ~/sverk_rover/src/system/rover_bringup/config/rover_v1.yaml
```

Change at least these fields:

```yaml
robot:
  id: rover-02
  hostname: rover-02
  serial_number: SVR-0002
```

Meaning:

```text
robot.id       Main software identity used by agent and fleet bridge.
hostname       Expected Linux/network hostname for humans and UI.
serial_number  Physical production serial number.
```

The agent and server bridge read `robot.id` indirectly through
`@robot.id` in:

```text
src/system/rover_bringup/config/components/agent.yaml
```

Do not give two active rovers the same `robot.id`. If two rovers share an ID,
the server may show them as one robot, commands can be routed incorrectly, and
answers/status updates can overwrite each other.

## 4. Set ROS Domain

Edit the systemd environment file:

```bash
sudo nano /etc/default/rover-bringup
```

Set a unique ROS domain:

```bash
ROS_DOMAIN_ID=2
```

Recommended:

```text
rover-01 -> ROS_DOMAIN_ID=1
rover-02 -> ROS_DOMAIN_ID=2
rover-03 -> ROS_DOMAIN_ID=3
```

Why this matters: ROS 2 discovery is network-visible. If several rovers share
the same ROS domain in one network, they can see each other's `/cmd_vel`,
`/odom`, `/scan`, `/tf`, and other topics. For fleet/server operation this is
usually not wanted. The rover-to-server bridge communicates through MQTT, so
rovers do not need to share a ROS domain.

If you intentionally want to debug multiple rovers from one ROS laptop, set the
laptop to the same `ROS_DOMAIN_ID` as the rover you are inspecting.

## 5. Check Server And MQTT Settings

Main config:

```text
src/system/rover_bringup/config/components/agent.yaml
```

Usually the server address is shared by all rovers:

```yaml
fleet_bridge:
  mqtt_host: 10.63.18.111
  mqtt_port: 1883
  mqtt_topic_prefix: fleet/v1/robots
```

Usually this must stay as a reference:

```yaml
fleet_bridge:
  robot_id: '@robot.id'

text_agent:
  robot_id: '@robot.id'
```

Do not hardcode the same `robot_id` in `agent.yaml` for every rover.

If the MQTT server uses per-robot credentials, set unique credentials in:

```bash
sudo nano /etc/default/rover-bringup
```

Example:

```bash
FLEET_MQTT_USERNAME=rover-02
FLEET_MQTT_PASSWORD=change-me
```

If the server uses shared credentials and distinguishes rovers only by
`robot.id`, these values may be the same for all rovers.

## 6. Configure Launch Profile And Components

In `/etc/default/rover-bringup`, choose the default service launch mode:

```bash
ROVER_PROFILE=full
ROVER_DISCOVERY_MODE=configured
```

`rover-bringup` starts the main ROS stack without the web UI. The web UI is
started separately by `rover-web.service`, with its own environment file:

```bash
sudo nano /etc/default/rover-web
```

Typical web settings:

```bash
ROVER_WEB_BIND_ADDRESS=0.0.0.0
ROVER_WEB_PORT=8765
ROVER_WEB_USE_ROSBOARD=true
```

Optional component overrides:

```bash
ROVER_LAUNCH_ARGS="use_waveshare_audio:=true"
```

More examples:

```bash
ROVER_LAUNCH_ARGS="use_camera:=false"
ROVER_LAUNCH_ARGS="use_agent:=false use_fleet_bridge:=false"
ROVER_LAUNCH_ARGS="use_waveshare_audio:=true use_camera:=false"
```

For multiple rovers connected to one server, the normal production profile is
usually:

```bash
ROVER_PROFILE=full
```

The `full` profile includes local agent and fleet bridge in the current rover
configuration.

## 7. Recreate Physical Device Mapping

The image may contain serial-device mapping from the source rover:

```text
~/.config/rover/devices.json
```

Recreate it on each physical rover:

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run rover_device_manager setup_devices
```

Follow the prompts and connect devices in the requested order.

This step is important because cloned USB paths and saved metadata can point to
the wrong physical devices on another rover.

Normal runtime aliases are created in:

```text
/tmp/rover_devices/
```

Expected aliases:

```text
/tmp/rover_devices/motor_controller
/tmp/rover_devices/imu
/tmp/rover_devices/lidar
```

## 8. Rebuild Workspace

If you changed files inside `~/sverk_rover/src`, rebuild:

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

If only `/etc/default/rover-bringup` or `/etc/default/rover-web` changed,
rebuilding is not required.

## 9. Restart Service

Reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart rover-bringup
sudo systemctl restart rover-web
```

Check status:

```bash
systemctl status rover-bringup
systemctl status rover-web
journalctl -u rover-bringup -f
journalctl -u rover-web -f
```

If the service is not installed yet:

```bash
cd ~/sverk_rover
deploy/systemd/install.sh
sudo systemctl start rover-bringup
sudo systemctl start rover-web
```

## 10. Verify Local Rover State

Check identity config:

```bash
grep -A8 '^robot:' ~/sverk_rover/src/system/rover_bringup/config/rover_v1.yaml
```

Check service environment:

```bash
grep -E 'ROVER_PROFILE|ROS_DOMAIN_ID|ROVER_LAUNCH_ARGS|FLEET_MQTT' /etc/default/rover-bringup
```

Check ROS graph:

```bash
source /opt/ros/jazzy/setup.bash
source ~/sverk_rover/install/setup.bash
echo "$ROS_DOMAIN_ID"
ros2 node list
```

Check agent and fleet bridge logs:

```bash
journalctl -u rover-bringup -f | grep -E 'fleet_text_bridge|rover_agent|robot_id|mqtt'
```

Check server UI:

```text
The rover should appear as its unique robot.id, for example rover-02.
```

## 11. Verify Multiple Rovers

For two active rovers, confirm:

```text
rover-01:
  robot.id: rover-01
  hostname: rover-01
  serial_number: SVR-0001
  ROS_DOMAIN_ID=1

rover-02:
  robot.id: rover-02
  hostname: rover-02
  serial_number: SVR-0002
  ROS_DOMAIN_ID=2
```

Both can use the same:

```text
mqtt_host
mqtt_port
mqtt_topic_prefix
llm_base_url
llm_model
```

They should not share:

```text
robot.id
hostname
serial_number
ROS_DOMAIN_ID
~/.config/rover/devices.json copied from another physical rover
```

## Troubleshooting

### Server shows rover offline

Check:

```bash
journalctl -u rover-bringup -f | grep fleet_text_bridge
```

Common causes:

```text
Wrong mqtt_host or mqtt_port.
Wrong MQTT username/password.
fleet_bridge disabled.
robot.id mismatch between rover and server expectation.
Network cannot reach MQTT broker.
```

### Server receives commands but rover does not answer

Check for robot ID mismatch warnings:

```bash
journalctl -u rover-bringup -f | grep -E 'robot_id|Ignored ROS status|Invalid ROS answer'
```

If logs show a mismatch, fix `robot.id` in:

```text
src/system/rover_bringup/config/rover_v1.yaml
```

### Two rovers react to one ROS command

They are probably in the same ROS domain. Set unique values:

```bash
sudo nano /etc/default/rover-bringup
```

```bash
ROS_DOMAIN_ID=2
```

Restart:

```bash
sudo systemctl restart rover-bringup
sudo systemctl restart rover-web
```

### Wrong serial device is used

Re-run setup on that physical rover:

```bash
ros2 run rover_device_manager setup_devices
sudo systemctl restart rover-bringup
sudo systemctl restart rover-web
```

If needed, inspect:

```bash
cat ~/.config/rover/devices.json
ls -l /tmp/rover_devices
```

### Hostname changed but network still shows old name

Reboot after hostname changes:

```bash
sudo reboot
```

Also check `/etc/hosts`.

## Per-Rover Setup Checklist

Use this checklist after cloning an image:

```text
[ ] Stop rover-bringup service.
[ ] Set unique Linux hostname.
[ ] Update /etc/hosts.
[ ] Set robot.id in rover_v1.yaml.
[ ] Set robot.hostname in rover_v1.yaml.
[ ] Set robot.serial_number in rover_v1.yaml.
[ ] Set unique ROS_DOMAIN_ID in /etc/default/rover-bringup.
[ ] Set MQTT credentials if this rover has unique credentials.
[ ] Configure ROVER_PROFILE and ROVER_LAUNCH_ARGS.
[ ] Re-run ros2 run rover_device_manager setup_devices.
[ ] Rebuild workspace if repository files changed.
[ ] Restart rover-bringup.
[ ] Confirm unique robot appears online on the server.
[ ] Confirm commands and answers are routed to this rover only.
```
