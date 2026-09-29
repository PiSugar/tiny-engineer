from __future__ import annotations

import json
import mmap
import socket
import threading
import time
from pathlib import Path
from typing import Callable


class WhisplayDaemon:
    WIDTH = 240
    HEIGHT = 280

    def __init__(self, socket_path: str = "/tmp/whisplay-daemon.sock"):
        self.socket_path = socket_path
        self.app_id = "tiny-engineer"
        self._token: str | None = None
        self._fb_file = None
        self._framebuffer: mmap.mmap | None = None
        self._stride = self.WIDTH * 2
        self._running = False
        self.on_button: Callable[[], None] | None = None
        self.on_exit: Callable[[], None] | None = None

    def request(self, command: str, payload: dict | None = None) -> dict:
        body = {"version": 1, "cmd": command, "payload": payload or {}}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(self.socket_path)
            client.sendall((json.dumps(body) + "\n").encode())
            with client.makefile("r") as reader:
                response = json.loads(reader.readline())
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "whisplay-daemon request failed"))
        return response.get("payload", {})

    def connect(self, launch_command: str, cwd: str) -> None:
        self.request("health.ping")
        self.request("app.register", {
            "app_id": self.app_id,
            "display_name": "Tiny Engineer",
            "icon": "TE",
            "launch_command": launch_command,
            "cwd": cwd,
            "exit_gesture": "quad_click",
            "priority": 60,
            "use_daemon_default_log": True,
            "persist": True,
        })
        focus = self.request("app.focus.acquire", {"app_id": self.app_id})
        self._token = focus["session_token"]
        fb = self.request("framebuffer.acquire", {
            "app_id": self.app_id,
            "session_token": self._token,
        })
        self._stride = int(fb["stride"])
        self._fb_file = open(fb["buffer_handle"], "r+b")
        self._framebuffer = mmap.mmap(self._fb_file.fileno(), 0)
        self._running = True
        threading.Thread(target=self._event_loop, daemon=True).start()

    def set_led(self, red: int, green: int, blue: int, fade_ms: int = 150) -> None:
        try:
            self.request("led.fade", {
                "r": red, "g": green, "b": blue, "duration_ms": fade_ms,
            })
        except (OSError, RuntimeError):
            pass

    def draw(self, image) -> None:
        if self._framebuffer is None:
            return
        rgb = image.convert("RGB")
        pixels = bytearray()
        for red, green, blue in rgb.getdata():
            value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
            pixels.extend((value >> 8, value & 0xFF))
        try:
            self._framebuffer.seek(0)
            self._framebuffer.write(pixels)
        except (ValueError, BufferError):
            pass

    def _event_loop(self) -> None:
        while self._running:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(self.socket_path)
                    body = {"version": 1, "cmd": "events.subscribe", "payload": {"app_id": self.app_id}}
                    client.sendall((json.dumps(body) + "\n").encode())
                    reader = client.makefile("r")
                    reader.readline()
                    for line in reader:
                        if not self._running:
                            return
                        event = json.loads(line)
                        if event.get("event") == "button_released" and self.on_button:
                            self.on_button()
                        elif event.get("event") in ("app_exit_requested", "app_focus_revoked"):
                            if self.on_exit:
                                self.on_exit()
                            return
            except (OSError, ValueError):
                time.sleep(0.5)

    def close(self) -> None:
        self._running = False
        if self._token:
            try:
                self.request("app.focus.release", {"app_id": self.app_id, "session_token": self._token})
            except (OSError, RuntimeError):
                pass
        if self._framebuffer is not None:
            self._framebuffer.close()
        if self._fb_file is not None:
            self._fb_file.close()
        self._framebuffer = None
        self._fb_file = None


def register_app(repo_root: Path) -> None:
    daemon = WhisplayDaemon()
    launch = str(repo_root / "raspberry_pi" / "run.sh")
    daemon.request("app.register", {
        "app_id": daemon.app_id,
        "display_name": "Tiny Engineer",
        "icon": "TE",
        "launch_command": launch,
        "cwd": str(repo_root),
        "exit_gesture": "quad_click",
        "priority": 60,
        "use_daemon_default_log": True,
        "persist": True,
    })
