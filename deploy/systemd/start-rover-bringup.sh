#!/usr/bin/env bash
set -eo pipefail

ROVER_WS="${ROVER_WS:-/home/pi/sverk_rover}"

core_profile="${ROVER_CORE_PROFILE:-}"
if [[ -z "${core_profile}" ]]; then
  case "${ROVER_PROFILE:-full}" in
    agent) core_profile="none" ;;
    minimal) core_profile="minimal" ;;
    hardware) core_profile="hardware" ;;
    mapping) core_profile="mapping" ;;
    *) core_profile="full" ;;
  esac
fi

cd "${ROVER_WS}"
source /opt/ros/jazzy/setup.bash
source "${ROVER_WS}/install/setup.bash"

launch_args=()
if [[ -n "${ROVER_LAUNCH_ARGS:-}" ]]; then
  # Keep backward compatibility with the old shared argument list, but only
  # forward options owned by the core layer.
  # shellcheck disable=SC2206
  configured_args=(${ROVER_LAUNCH_ARGS})
  for arg in "${configured_args[@]}"; do
    case "${arg}" in
      use_web:=*) ;;
      use_rosboard:=*) ;;
      use_display:=*) ;;
      use_agent:=*) ;;
      use_fleet_bridge:=*) ;;
      use_nav2:=*) ;;
      use_slam:=*) ;;
      mode:=*) ;;
      profile:=*) ;;
      *) launch_args+=("${arg}") ;;
    esac
  done
fi

exec ros2 launch rover_bringup core.launch.py \
  "profile:=${core_profile}" \
  "discovery_mode:=${ROVER_DISCOVERY_MODE:-configured}" \
  "${launch_args[@]}"
