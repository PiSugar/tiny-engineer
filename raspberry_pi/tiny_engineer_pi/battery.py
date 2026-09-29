from __future__ import annotations

import socket
import threading


class BatteryMonitor:
    """PiSugar status client matching whisplay-xiaozhi's TCP protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8423):
        self.host = host
        self.port = port
        self.level = -1
        self.charging = False
        self._lock = threading.Lock()

    def _command(self, reader, writer, command: str) -> str:
        writer.write((command + "\n").encode())
        writer.flush()
        return reader.readline().decode(errors="replace").strip()

    def query(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=3) as client:
            client.settimeout(3)
            reader = client.makefile("rb")
            writer = client.makefile("wb")
            battery = self._command(reader, writer, "get battery")
            charging = self._command(reader, writer, "get battery_charging")
        level = -1
        if battery.startswith("battery:"):
            level = max(0, min(100, int(float(battery.split(":", 1)[1].strip()))))
        with self._lock:
            self.level = level
            self.charging = "true" in charging.lower()

    def snapshot(self) -> tuple[int, bool]:
        with self._lock:
            return self.level, self.charging

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.query()
            except (OSError, ValueError):
                with self._lock:
                    self.level = -1
                    self.charging = False
            stop_event.wait(5)

