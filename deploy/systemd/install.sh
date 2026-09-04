#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

SERVICE_NAMES=(
  "rover-bringup.service"
  "rover-web.service"
  "rover-mode.service"
  "rover-integrations.service"
)
RUN_USER="${ROVER_SERVICE_USER:-pi}"
RUN_GROUP="${ROVER_SERVICE_GROUP:-${RUN_USER}}"
WORKSPACE="${ROVER_WS:-${REPO_ROOT}}"

if [[ ! -f "${WORKSPACE}/install/setup.bash" ]]; then
  cat >&2 <<EOF
Workspace install/setup.bash was not found:
  ${WORKSPACE}/install/setup.bash

Build the workspace first, or pass the workspace path explicitly:
  ROVER_WS=/home/pi/sverk_rover ${SCRIPT_DIR}/install.sh
EOF
  exit 1
fi

for service_name in "${SERVICE_NAMES[@]}"; do
  service_src="${SCRIPT_DIR}/${service_name}"
  service_dst="/etc/systemd/system/${service_name}"

  tmp_service="$(mktemp)"
  sed \
    -e "s|^User=.*|User=${RUN_USER}|" \
    -e "s|^Group=.*|Group=${RUN_GROUP}|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=${WORKSPACE}|" \
    "${service_src}" > "${tmp_service}"

  sudo install -m 0644 "${tmp_service}" "${service_dst}"
  rm -f "${tmp_service}"
done

for env_name in rover-bringup rover-web rover-mode rover-integrations; do
  env_src="${SCRIPT_DIR}/${env_name}.env"
  env_dst="/etc/default/${env_name}"

  if [[ ! -f "${env_dst}" ]]; then
    tmp_env="$(mktemp)"
    sed -e "s|^ROVER_WS=.*|ROVER_WS=${WORKSPACE}|" "${env_src}" > "${tmp_env}"
    sudo install -m 0640 -o root -g "${RUN_GROUP}" "${tmp_env}" "${env_dst}"
    rm -f "${tmp_env}"
  else
    echo "Keeping existing ${env_dst}"
  fi
done

sudo systemctl daemon-reload
for service_name in "${SERVICE_NAMES[@]}"; do
  sudo systemctl enable "${service_name}"
done

cat <<EOF
Installed rover-bringup, rover-web, rover-mode and rover-integrations services.

Edit launch settings:
  sudo nano /etc/default/rover-bringup
  sudo nano /etc/default/rover-web
  sudo nano /etc/default/rover-mode
  sudo nano /etc/default/rover-integrations

Start/stop/status:
  sudo systemctl start rover-bringup
  sudo systemctl start rover-web
  sudo systemctl start rover-mode
  sudo systemctl start rover-integrations
  sudo systemctl stop rover-integrations
  sudo systemctl stop rover-mode
  sudo systemctl stop rover-web
  sudo systemctl stop rover-bringup
  systemctl status rover-bringup
  systemctl status rover-web
  systemctl status rover-mode
  systemctl status rover-integrations

Logs:
  journalctl -u rover-bringup -f
  journalctl -u rover-web -f
  journalctl -u rover-mode -f
  journalctl -u rover-integrations -f
EOF
