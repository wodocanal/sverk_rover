#!/usr/bin/env bash
set -eo pipefail

ROVER_WS="${ROVER_WS:-/home/pi/sverk_rover}"

mode="${ROVER_MODE:-}"
if [[ -z "${mode}" ]]; then
  case "${ROVER_PROFILE:-full}" in
    mapping) mode="mapping" ;;
    full|navigation) mode="navigation" ;;
    *) mode="idle" ;;
  esac
fi

cd "${ROVER_WS}"
source /opt/ros/jazzy/setup.bash
source "${ROVER_WS}/install/setup.bash"

launch_args=()
if [[ -n "${ROVER_MODE_LAUNCH_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  launch_args=(${ROVER_MODE_LAUNCH_ARGS})
fi

exec ros2 launch rover_bringup mode.launch.py \
  "mode:=${mode}" \
  "use_rviz:=${ROVER_MODE_USE_RVIZ:-false}" \
  "start_delay:=${ROVER_MODE_START_DELAY:-2.0}" \
  "${launch_args[@]}"
