#!/usr/bin/env bash
set -euo pipefail

world="${1:-empty}"
mode="${2:-idle}"
ui="${3:-web}"
display="${DISPLAY:-:99}"
resolution="${GAZEBO_GUI_RESOLUTION:-1600x1000}"
password="${GAZEBO_GUI_PASSWORD:-rover}"

if [[ ! "${resolution}" =~ ^[0-9]+x[0-9]+$ ]]; then
  echo "Invalid GAZEBO_GUI_RESOLUTION=${resolution}" >&2
  exit 2
fi

export DISPLAY="${display}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/rover-gazebo-runtime}"
export QT_X11_NO_MITSHM=1
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export GALLIUM_DRIVER="${GALLIUM_DRIVER:-llvmpipe}"

mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}"

xvfb_pid=''
openbox_pid=''
vnc_pid=''
ros_pid=''
cleanup() {
  [[ -z "${ros_pid}" ]] || kill -TERM "${ros_pid}" >/dev/null 2>&1 || true
  [[ -z "${vnc_pid}" ]] || kill -TERM "${vnc_pid}" >/dev/null 2>&1 || true
  [[ -z "${openbox_pid}" ]] || kill -TERM "${openbox_pid}" >/dev/null 2>&1 || true
  [[ -z "${xvfb_pid}" ]] || kill -TERM "${xvfb_pid}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

Xvfb "${display}" -screen 0 "${resolution}x24" \
  -nolisten tcp +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
xvfb_pid=$!

for _ in {1..80}; do
  xdpyinfo -display "${display}" >/dev/null 2>&1 && break
  kill -0 "${xvfb_pid}" >/dev/null 2>&1 || {
    cat /tmp/xvfb.log >&2
    exit 1
  }
  sleep 0.1
done

if ! xdpyinfo -display "${display}" >/dev/null 2>&1; then
  echo "Virtual X display ${display} did not become ready." >&2
  cat /tmp/xvfb.log >&2
  exit 1
fi

echo "Gazebo GUI OpenGL renderer:"
glxinfo -B 2>&1 | sed -n '1,16p'

openbox >/tmp/openbox.log 2>&1 &
openbox_pid=$!
x11vnc -display "${display}" -rfbport 5901 -listen 0.0.0.0 \
  -forever -shared -passwd "${password}" -noxdamage -repeat -quiet \
  >/tmp/x11vnc.log 2>&1 &
vnc_pid=$!

for _ in {1..50}; do
  (echo >/dev/tcp/127.0.0.1/5901) >/dev/null 2>&1 && break
  kill -0 "${vnc_pid}" >/dev/null 2>&1 || {
    cat /tmp/x11vnc.log >&2
    exit 1
  }
  sleep 0.1
done

if ! (echo >/dev/tcp/127.0.0.1/5901) >/dev/null 2>&1; then
  echo "VNC server did not become ready." >&2
  cat /tmp/x11vnc.log >&2
  exit 1
fi

ros2 launch rover_bringup simulation.launch.py \
  "world:=${world}" "mode:=${mode}" "ui_profile:=${ui}" \
  gui:=true headless_rendering:=false &
ros_pid=$!
wait "${ros_pid}"
