#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAMES=(
  "rover-bringup.service"
  "rover-web.service"
  "rover-mode.service"
  "rover-integrations.service"
)

for service_name in "${SERVICE_NAMES[@]}"; do
  sudo systemctl disable --now "${service_name}" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/${service_name}"
done
sudo systemctl daemon-reload

cat <<EOF
Removed rover-bringup, rover-web, rover-mode and rover-integrations services.

The environment files were left in place:
  /etc/default/rover-bringup
  /etc/default/rover-web
  /etc/default/rover-mode
  /etc/default/rover-integrations

Remove them manually if they are no longer needed.
EOF
