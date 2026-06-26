#!/usr/bin/env bash
set -euo pipefail

workspace="${1:-${ROVER_WORKSPACE:-$HOME/sverk_rover}}"

if [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/jazzy/setup.bash
fi

if [ -f "$workspace/install/setup.bash" ]; then
  # shellcheck disable=SC1090
  source "$workspace/install/setup.bash"
fi

if [ -d "$workspace" ]; then
  cd "$workspace"
else
  cd "$HOME"
fi

export ROVER_WORKSPACE="$workspace"

if command -v zsh >/dev/null 2>&1; then
  exec zsh -i
fi

exec bash -i
