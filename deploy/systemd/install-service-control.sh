#!/usr/bin/env bash
# Run once on the rover as root; does not restart or stop either service.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run: sudo bash deploy/systemd/install-service-control.sh" >&2
  exit 1
fi

SYSTEMCTL="$(command -v systemctl)"
SYSTEMCTL="$(readlink -f "${SYSTEMCTL}")"
if [[ "${SYSTEMCTL}" != /usr/bin/systemctl && "${SYSTEMCTL}" != /bin/systemctl ]]; then
  echo "Unsupported systemctl location: ${SYSTEMCTL}" >&2
  exit 1
fi
command -v sudo >/dev/null
command -v visudo >/dev/null

RUN_USER="${ROVER_SERVICE_USER:-}"
if [[ -z "${RUN_USER}" ]]; then
  if [[ "$("${SYSTEMCTL}" show rover-web.service --property=LoadState --value)" != loaded ]]; then
    echo "rover-web.service is not installed; run deploy/systemd/install.sh first." >&2
    exit 1
  fi
  RUN_USER="$("${SYSTEMCTL}" show rover-web.service --property=User --value)"
  RUN_USER="${RUN_USER:-root}"
fi
if [[ ! "${RUN_USER}" =~ ^[a-z_][a-z0-9_-]*\$?$ ]]; then
  echo "Invalid service user" >&2
  exit 1
fi
id "${RUN_USER}" >/dev/null

tmp_policy="$(mktemp)"
trap 'rm -f "${tmp_policy}"' EXIT
# Exact arguments only: no shell, wildcard, user-provided unit or daemon-reload.
printf '%s ALL=(root) NOPASSWD: %s --no-ask-password start rover-bringup.service, %s --no-ask-password stop rover-bringup.service, %s --no-ask-password --no-block restart rover-web.service\n' \
  "${RUN_USER}" "${SYSTEMCTL}" "${SYSTEMCTL}" "${SYSTEMCTL}" > "${tmp_policy}"
visudo -cf "${tmp_policy}"
install -d -o root -g root -m 0755 /etc/sudoers.d
install -o root -g root -m 0440 "${tmp_policy}" /etc/sudoers.d/rover-service-control

# sudo -l checks authorization without starting/stopping hardware.
sudo -u "${RUN_USER}" -- sudo -n -l -- "${SYSTEMCTL}" --no-ask-password start rover-bringup.service >/dev/null
sudo -u "${RUN_USER}" -- sudo -n -l -- "${SYSTEMCTL}" --no-ask-password stop rover-bringup.service >/dev/null
sudo -u "${RUN_USER}" -- sudo -n -l -- "${SYSTEMCTL}" --no-ask-password --no-block restart rover-web.service >/dev/null
echo "Verified limited service control for ${RUN_USER}. No services were restarted."
echo "Permissions file: /etc/sudoers.d/rover-service-control"
