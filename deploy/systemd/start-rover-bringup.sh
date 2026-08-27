#!/usr/bin/env bash
set -eo pipefail

ROVER_WS="${ROVER_WS:-/home/pi/sverk_rover}"

cd "${ROVER_WS}"
source /opt/ros/jazzy/setup.bash
source "${ROVER_WS}/install/setup.bash"

launch_args=()
if [[ -n "${ROVER_LAUNCH_ARGS:-}" ]]; then
  # ROVER_LAUNCH_ARGS is intentionally shell-style, for simple name:=value args.
  # shellcheck disable=SC2206
  configured_args=(${ROVER_LAUNCH_ARGS})
  for arg in "${configured_args[@]}"; do
    case "${arg}" in
      use_web:=*) ;;
      use_rosboard:=*) ;;
      *) launch_args+=("${arg}") ;;
    esac
  done
fi

exec ros2 launch rover_bringup robot.launch.py \
  "profile:=${ROVER_PROFILE:-full}" \
  "discovery_mode:=${ROVER_DISCOVERY_MODE:-configured}" \
  "use_web:=${ROVER_BRINGUP_USE_WEB:-false}" \
  "use_rosboard:=${ROVER_BRINGUP_USE_ROSBOARD:-false}" \
  "${launch_args[@]}"
