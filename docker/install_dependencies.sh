#!/usr/bin/env bash
set -euo pipefail

source_path="${1:?Pass the workspace source directory}"
ros_distro="${ROS_DISTRO:-jazzy}"

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  rosdep init
fi

rosdep_cache="${HOME}/.ros/rosdep/sources.cache"
if [[ "${ROVER_ROSDEP_UPDATE:-0}" == "1" || ! -d "${rosdep_cache}" ]]; then
  for attempt in 1 2 3; do
    if rosdep update --rosdistro "${ros_distro}"; then
      break
    fi
    if [[ "${attempt}" -eq 3 ]]; then
      echo "rosdep update remained partial after ${attempt} attempts;" \
        "continuing with the downloaded cache." >&2
      echo "rosdep install will still fail if a required key is unavailable." >&2
      break
    fi
    echo "rosdep update attempt ${attempt} failed; retrying..." >&2
    sleep $((attempt * 3))
  done
else
  echo "Using rosdep cache bundled with the ROS base image."
  echo "Set ROVER_ROSDEP_UPDATE=1 to refresh it explicitly."
fi

apt-get update
apt-get install -y --no-install-recommends python3-spidev

rosdep install \
  --from-paths "${source_path}" \
  --ignore-src \
  --rosdistro "${ros_distro}" \
  --dependency-types build \
  --dependency-types buildtool \
  --dependency-types build_export \
  --dependency-types buildtool_export \
  --dependency-types exec \
  --dependency-types test \
  --as-root pip:false \
  --skip-keys 'ament_python python3-spidev' \
  -r -y
