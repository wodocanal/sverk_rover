#!/usr/bin/env bash
set +u

WORKSPACE_ROOT="${1:-$HOME/sverk_rover}"

export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"

source /opt/ros/jazzy/setup.bash

if [ -f "${WORKSPACE_ROOT}/install/setup.bash" ]; then
    source "${WORKSPACE_ROOT}/install/setup.bash"
fi

cd "${WORKSPACE_ROOT}" || exit 1
exec /bin/bash --noprofile --rcfile "${HOME}/.bashrc" -i
