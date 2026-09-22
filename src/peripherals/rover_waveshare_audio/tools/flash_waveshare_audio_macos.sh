#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:/opt/homebrew/bin:${PATH}"

IDF_EXPORT="${IDF_EXPORT:-${HOME}/esp/esp-idf/export.sh}"
if [[ -f "${IDF_EXPORT}" ]]; then
  # shellcheck source=/dev/null
  source "${IDF_EXPORT}"
fi

PYTHON="${PYTHON:-python3}"
exec "${PYTHON}" "${SCRIPT_DIR}/flash_waveshare_audio.py" "$@"
