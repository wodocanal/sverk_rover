#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This launcher opens the macOS Screen Sharing application." >&2
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is not running. Start it and retry 'make sim-gui'." >&2
  exit 2
fi

port="${SIM_GUI_PORT:-5901}"
resolution="${SIM_GUI_RESOLUTION:-1600x1000}"
world="${SIM_WORLD:-empty}"
mode="${SIM_MODE:-idle}"
ui="${SIM_UI:-web}"
service="${GUI_SERVICE:-ros-gui}"
password="rover"

if [[ ! "${port}" =~ ^[0-9]+$ ]] || ((port < 1024 || port > 65535)); then
  echo "SIM_GUI_PORT must be an integer between 1024 and 65535." >&2
  exit 2
fi
if [[ ! "${resolution}" =~ ^[0-9]+x[0-9]+$ ]]; then
  echo "SIM_GUI_RESOLUTION must use WIDTHxHEIGHT, for example 1600x1000." >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

container_name="sverk-rover-gazebo-gui-${$}"
compose_pid=''
cleanup() {
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  if [[ -n "${compose_pid}" ]]; then
    wait "${compose_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 0' INT
trap 'exit 143' TERM

echo "Starting Gazebo GUI: world=${world}, mode=${mode}, ui=${ui}"
SIM_GUI_PORT="${port}" docker compose run --rm --service-ports --no-TTY \
  --name "${container_name}" \
  -e DISPLAY=:99 \
  -e GAZEBO_GUI_RESOLUTION="${resolution}" \
  -e GAZEBO_GUI_PASSWORD="${password}" \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  -e GALLIUM_DRIVER=llvmpipe \
  "${service}" \
  bash docker/gazebo_gui_entrypoint.sh "${world}" "${mode}" "${ui}" &
compose_pid=$!

for _ in {1..120}; do
  if nc -z 127.0.0.1 "${port}" >/dev/null 2>&1; then
    # x11vnc opens the TCP port slightly before its authentication handshake
    # is ready; Screen Sharing does not retry that transient failure.
    sleep 2
    echo "Opening macOS Screen Sharing at vnc://127.0.0.1:${port}"
    open "vnc://:${password}@127.0.0.1:${port}"
    wait "${compose_pid}"
    exit $?
  fi
  if ! kill -0 "${compose_pid}" >/dev/null 2>&1; then
    wait "${compose_pid}"
    exit $?
  fi
  sleep 0.25
done

echo "Gazebo graphical desktop did not become ready on port ${port}." >&2
exit 1
