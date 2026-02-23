#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-8000}"

usage() {
  cat <<'EOF'
One-command NES emulator setup + run.

Usage:
  ./run_emulator.sh                 # setup + run web UI on :8000
  ./run_emulator.sh web [port]      # setup + run web UI on [port]
  ./run_emulator.sh cli <rom_path>  # setup + run CLI emulator on ROM
  ./run_emulator.sh setup-only      # install dependencies only
EOF
}

MODE="${1:-web}"

if [[ "${MODE}" == "-h" || "${MODE}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip
python -m pip install -e "${ROOT_DIR}"

case "${MODE}" in
  web)
    if [[ $# -ge 2 ]]; then
      PORT="$2"
    fi
    exec nes-emulator-web --host 0.0.0.0 --port "${PORT}"
    ;;
  cli)
    if [[ $# -lt 2 ]]; then
      echo "Error: ROM path is required for cli mode." >&2
      usage
      exit 1
    fi
    shift
    exec nes-emulator "$@"
    ;;
  setup-only)
    echo "Setup complete. Activate with: source .venv/bin/activate"
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    usage
    exit 1
    ;;
esac
