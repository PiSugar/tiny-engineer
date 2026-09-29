#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OWNER="${SUDO_USER:-pi}"

apt-get update
apt-get install -y python3-venv python3-pip python3-pil python3-smbus i2c-tools alsa-utils
python3 -m venv --system-site-packages "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

if [[ ! -f "$SCRIPT_DIR/config.json" ]]; then
  cp "$SCRIPT_DIR/config.example.json" "$SCRIPT_DIR/config.json"
fi
chown -R "$OWNER":"$OWNER" "$SCRIPT_DIR/.venv" "$SCRIPT_DIR/config.json"
chmod +x "$SCRIPT_DIR/run.sh" "$SCRIPT_DIR/run_service.sh"

BOOT_CONFIG=/boot/firmware/config.txt
if [[ ! -f "$BOOT_CONFIG" ]]; then
  BOOT_CONFIG=/boot/config.txt
fi
if ! grep -q '^dtparam=i2c_arm=on' "$BOOT_CONFIG" 2>/dev/null; then
  echo 'dtparam=i2c_arm=on' >> "$BOOT_CONFIG"
fi

cd "$SCRIPT_DIR"
if systemctl list-unit-files whisplay-daemon.service >/dev/null 2>&1; then
  systemctl start whisplay-daemon.service
fi
for _ in {1..20}; do
  [[ -S /tmp/whisplay-daemon.sock ]] && break
  sleep 0.25
done
if [[ ! -S /tmp/whisplay-daemon.sock ]]; then
  echo "whisplay-daemon is not running; install/start it, then run ./raspberry_pi/register.sh" >&2
  exit 1
fi
sudo -u "$OWNER" "$SCRIPT_DIR/.venv/bin/python" -m tiny_engineer_pi.app --register

REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
sed \
  -e "s|@OWNER@|$OWNER|g" \
  -e "s|@ROOT@|$REPO_ROOT|g" \
  "$SCRIPT_DIR/tiny-engineer.service.in" > /etc/systemd/system/tiny-engineer.service
systemctl daemon-reload
systemctl enable --now tiny-engineer.service

echo "Installed. Robot control and Web run in tiny-engineer.service."
echo "Select Tiny Engineer in the Whisplay launcher to open its remote-control app."
