#!/usr/bin/env bash
set -eo pipefail

ROVER_WS="${ROVER_WS:-/home/pi/sverk_rover}"

cd "${ROVER_WS}"
source /opt/ros/jazzy/setup.bash
source "${ROVER_WS}/install/setup.bash"

launch_args=()
if [[ -n "${ROVER_WEB_LAUNCH_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  launch_args=(${ROVER_WEB_LAUNCH_ARGS})
fi

exec ros2 launch rover_bringup ui.launch.py \
  use_web:=true \
  use_display:=false \
  "use_rosboard:=${ROVER_WEB_USE_ROSBOARD:-true}" \
  "web_bind_address:=${ROVER_WEB_BIND_ADDRESS:-0.0.0.0}" \
  "web_port:=${ROVER_WEB_PORT:-8765}" \
  "command_topic:=${ROVER_WEB_COMMAND_TOPIC:-/cmd_vel}" \
  "rosboard_port:=${ROVER_WEB_ROSBOARD_PORT:-8888}" \
  "${launch_args[@]}"
