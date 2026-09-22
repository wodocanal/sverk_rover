#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOOL="${SCRIPT_DIR}/../../tools/flash_waveshare_audio.py"

export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:/opt/homebrew/bin:${PATH}"

IDF_EXPORT="${IDF_EXPORT:-${HOME}/esp/esp-idf/export.sh}"
if [[ -f "${IDF_EXPORT}" ]]; then
  # shellcheck source=/dev/null
  source "${IDF_EXPORT}"
fi

PYTHON="${PYTHON:-python3}"
exec "${PYTHON}" "${TOOL}" --firmware-dir "${SCRIPT_DIR}" "$@"
