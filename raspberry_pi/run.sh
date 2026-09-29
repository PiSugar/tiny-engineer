#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
CONFIG="${TINY_ENGINEER_CONFIG:-$SCRIPT_DIR/config.json}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Tiny Engineer is not installed. Run: sudo $SCRIPT_DIR/install.sh" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
exec "$PYTHON" -m tiny_engineer_pi.app --config "$CONFIG"
