from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .animation import ANIMATIONS
from .config import load_config
from .ui import render_ui
from .whisplay_daemon import WhisplayDaemon, register_app


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


class RobotServiceClient:
    def __init__(self, port: int):
        self.base_url = f"http://127.0.0.1:{port}"

    def health(self) -> dict:
        try:
            with urlopen(self.base_url + "/health", timeout=1) as response:
                return json.load(response)
        except (OSError, HTTPError, URLError, ValueError):
            return {"ok": False}

    def set_mode(self, mode: str) -> bool:
        request = Request(
            self.base_url + "/anim?" + urlencode({"name": mode}),
            method="POST",
        )
        try:
            with urlopen(request, timeout=2) as response:
                body = json.load(response)
            return bool(body.get("ok"))
        except (OSError, HTTPError, URLError, ValueError):
            return False


def run_app(config_path: str | None) -> int:
    """Whisplay foreground client; all robot hardware stays in the service."""
    root = repository_root()
    config = load_config(config_path)
    client = RobotServiceClient(config.port)
    stop = threading.Event()
    daemon = WhisplayDaemon()
    daemon.connect(str(root / "raspberry_pi" / "run.sh"), str(root))
    modes = list(ANIMATIONS)
    selected = 0
    state_lock = threading.Lock()
    current_mode = "none"
    battery = (-1, False)

    def refresh() -> None:
        nonlocal selected, current_mode, battery
        health = client.health()
        with state_lock:
            if not health.get("ok"):
                current_mode = "service offline"
                battery = (-1, False)
                return
            mode = health.get("animation", "none")
            if mode in modes:
                current_mode = mode
                selected = modes.index(mode)
            battery_body = health.get("battery", {})
            battery = (
                int(battery_body.get("level", -1)),
                bool(battery_body.get("charging", False)),
            )

    def next_mode() -> None:
        nonlocal selected
        with state_lock:
            selected = (selected + 1) % len(modes)
            mode = modes[selected]
        threading.Thread(target=client.set_mode, args=(mode,), daemon=True).start()

    daemon.on_button = next_mode
    daemon.on_exit = stop.set
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    try:
        while not stop.is_set():
            refresh()
            with state_lock:
                mode = current_mode
                next_action = modes[(selected + 1) % len(modes)]
                battery_snapshot = battery
            daemon.draw(render_ui(mode, next_action, battery_snapshot))
            stop.wait(0.25)
    finally:
        daemon.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tiny Engineer Whisplay client")
    parser.add_argument("--config", default=None)
    parser.add_argument("--register", action="store_true", help="register with whisplay-daemon and exit")
    args = parser.parse_args()
    if args.register:
        register_app(repository_root())
        return 0
    return run_app(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
