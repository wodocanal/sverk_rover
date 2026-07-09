#!/usr/bin/env bash
set -eo pipefail

workspace="${1:-${ROVER_WORKSPACE:-$HOME/sverk_rover}}"
bind_address="${2:-0.0.0.0}"
port="${3:-13337}"
auth_mode="${4:-password}"

workspace="$(cd "$(dirname "$workspace")" 2>/dev/null && pwd)/$(basename "$workspace")"

if [ ! -d "$workspace" ]; then
  workspace="$HOME"
fi

if ! command -v code-server >/dev/null 2>&1; then
  echo "code-server is not installed or not available in PATH" >&2
  exit 127
fi

export ROVER_WORKSPACE="$workspace"

if [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/jazzy/setup.bash
fi

if [ -f "$workspace/install/setup.bash" ]; then
  # shellcheck disable=SC1090
  source "$workspace/install/setup.bash"
fi

cd "$workspace" 2>/dev/null || cd "$HOME"

echo "Rover VS Code ready"
echo "Workspace: $PWD"
echo "Bind: ${bind_address}:${port}"
echo "Auth: ${auth_mode}"
echo

exec code-server \
  --bind-addr "${bind_address}:${port}" \
  --auth "${auth_mode}" \
  "$workspace"
