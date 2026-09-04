#!/usr/bin/env bash
set -eo pipefail

ROVER_WS="${ROVER_WS:-/home/pi/sverk_rover}"

cd "${ROVER_WS}"
source /opt/ros/jazzy/setup.bash
source "${ROVER_WS}/install/setup.bash"

launch_args=()
if [[ -n "${ROVER_INTEGRATIONS_LAUNCH_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  launch_args=(${ROVER_INTEGRATIONS_LAUNCH_ARGS})
elif [[ -n "${ROVER_LAUNCH_ARGS:-}" ]]; then
  # Preserve old use_agent/use_fleet_bridge overrides after service splitting.
  # shellcheck disable=SC2206
  configured_args=(${ROVER_LAUNCH_ARGS})
  for arg in "${configured_args[@]}"; do
    case "${arg}" in
      use_agent:=*) launch_args+=("${arg}") ;;
      use_fleet_bridge:=*) launch_args+=("${arg}") ;;
    esac
  done
fi

exec ros2 launch rover_bringup integrations.launch.py \
  "profile:=${ROVER_INTEGRATIONS_PROFILE:-full}" \
  "${launch_args[@]}"
