#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAMES=(
  "rover-bringup.service"
  "rover-web.service"
)

for service_name in "${SERVICE_NAMES[@]}"; do
  sudo systemctl disable --now "${service_name}" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/${service_name}"
done
sudo systemctl daemon-reload

cat <<EOF
Removed rover-bringup.service and rover-web.service.

The environment files were left in place:
  /etc/default/rover-bringup
  /etc/default/rover-web

Remove them manually if they are no longer needed.
EOF
