#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
CONFIG="${TINY_ENGINEER_CONFIG:-$SCRIPT_DIR/config.json}"

# A system service does not inherit the desktop session environment. Point
# ALSA's Pulse plugin at this user's PipeWire-Pulse socket so audio is mixed
# instead of opening the Whisplay hardware PCM exclusively.
if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
  XDG_RUNTIME_DIR="/run/user/$(id -u)"
  export XDG_RUNTIME_DIR
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Tiny Engineer is not installed. Run: sudo $SCRIPT_DIR/install.sh" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
exec "$PYTHON" -m tiny_engineer_pi.service --config "$CONFIG"
