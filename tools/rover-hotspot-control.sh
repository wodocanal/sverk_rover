#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="/run/rover-hotspot"
HOSTAPD_CONF="$RUNTIME_DIR/hostapd.conf"
HOSTAPD_PID="$RUNTIME_DIR/hostapd.pid"
DNSMASQ_CONF="$RUNTIME_DIR/dnsmasq.conf"
DNSMASQ_PID="$RUNTIME_DIR/dnsmasq.pid"

log() {
  echo "[rover-hotspot] $*"
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    log "This command must run as root"
    exit 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Required command is missing: $1"
    exit 1
  fi
}

pid_running() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return 1
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_runtime() {
  if pid_running "$DNSMASQ_PID"; then
    kill "$(cat "$DNSMASQ_PID")" 2>/dev/null || true
    sleep 1
  fi
  if pid_running "$HOSTAPD_PID"; then
    kill "$(cat "$HOSTAPD_PID")" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$DNSMASQ_PID" "$HOSTAPD_PID"
}

status_mode() {
  if pid_running "$HOSTAPD_PID"; then
    echo "share"
    exit 0
  fi
  if command -v networkctl >/dev/null 2>&1; then
    local iface="${1:-wlan0}"
    local status
    status="$(networkctl status "$iface" 2>/dev/null || true)"
    if echo "$status" | grep -q "Wi-Fi access point:"; then
      echo "connect"
      exit 0
    fi
  fi
  echo "disconnected"
}

start_hotspot() {
  require_root
  require_command hostapd
  require_command dnsmasq
  require_command ip
  require_command systemctl

  local iface="${1:-wlan0}"
  local ssid="${2:-Rover-AP}"
  local password="${3:-StrongPassword123}"
  local address_cidr="${4:-192.168.50.1/24}"
  local dhcp_start="${5:-192.168.50.10}"
  local dhcp_end="${6:-192.168.50.200}"
  local channel="${7:-1}"
  local country="${8:-RU}"
  local band="${9:-bg}"

  if [ "${#password}" -lt 8 ]; then
    log "Hotspot password must be at least 8 characters"
    exit 1
  fi

  local hw_mode="g"
  if [ "$band" = "a" ] || [ "$band" = "5GHz" ] || [ "$band" = "5ghz" ]; then
    hw_mode="a"
  fi

  mkdir -p "$RUNTIME_DIR"

  stop_runtime
  systemctl stop wpa_supplicant.service || true

  rfkill unblock wifi || true
  ip link set "$iface" down || true
  ip addr flush dev "$iface" || true
  ip link set "$iface" up

  cat >"$HOSTAPD_CONF" <<EOF
interface=$iface
driver=nl80211
ssid=$ssid
hw_mode=$hw_mode
channel=$channel
country_code=$country
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=$password
EOF

  cat >"$DNSMASQ_CONF" <<EOF
interface=$iface
bind-interfaces
port=0
dhcp-range=$dhcp_start,$dhcp_end,255.255.255.0,24h
dhcp-option=3,${address_cidr%/*}
dhcp-option=6,${address_cidr%/*}
EOF

  ip addr add "$address_cidr" dev "$iface"

  hostapd -B -P "$HOSTAPD_PID" "$HOSTAPD_CONF"
  dnsmasq --conf-file="$DNSMASQ_CONF" --pid-file="$DNSMASQ_PID"

  log "Hotspot started on $iface ($ssid)"
}

stop_hotspot() {
  require_root
  require_command ip

  local iface="${1:-wlan0}"

  stop_runtime
  ip addr flush dev "$iface" || true
  ip link set "$iface" down || true
  systemctl restart wpa_supplicant.service || true
  ip link set "$iface" up || true

  if command -v netplan >/dev/null 2>&1; then
    netplan apply || true
  fi

  log "Returned $iface to normal client mode"
}

command="${1:-}"
case "$command" in
  start)
    shift
    start_hotspot "$@"
    ;;
  stop)
    shift
    stop_hotspot "$@"
    ;;
  status)
    shift
    status_mode "$@"
    ;;
  *)
    echo "Usage: $0 {start|stop|status} ..." >&2
    exit 2
    ;;
esac
