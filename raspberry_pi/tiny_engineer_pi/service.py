from __future__ import annotations

import argparse
import signal
import threading
import time
from pathlib import Path

from .animation import LED_COLORS, Animator
from .battery import BatteryMonitor
from .config import load_config
from .hardware import AudioDevice, open_servo_controller
from .http_api import ApiServer
from .oled import EyeDisplay
from .whisplay_daemon import WhisplayDaemon


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_service(config_path: str | None) -> int:
    """Own robot hardware and HTTP independently of the Whisplay foreground app."""
    root = repository_root()
    config = load_config(config_path)
    stop = threading.Event()
    servos = open_servo_controller(config)
    audio = AudioDevice(config.alsa_playback_device, config.alsa_capture_device)
    oled = EyeDisplay(
        config.i2c_bus,
        config.oled_address,
        config.oled_rotate_180,
        servo_angles=servos.snapshot,
    )
    animator = Animator(servos, audio, root / "assets")
    battery = BatteryMonitor()
    whisplay = WhisplayDaemon()
    asleep = False

    def apply_mode(mode: str) -> None:
        nonlocal asleep
        whisplay.set_led(*LED_COLORS[mode])
        if mode == "sleep":
            asleep = True
            oled.show_mode(mode)
        elif mode != "none" or not asleep:
            asleep = False
            oled.show_mode(mode)

    def test_led() -> None:
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
            whisplay.set_led(*color, fade_ms=0)
            time.sleep(0.5)
        whisplay.set_led(*LED_COLORS[animator.mode])

    def test_screen() -> None:
        current = animator.mode
        oled.show_mode("welcome")
        time.sleep(2)
        oled.show_mode(current)

    api = ApiServer(
        config.host,
        config.port,
        animator,
        servos,
        audio,
        config,
        test_led=test_led,
        test_screen=lambda: threading.Thread(target=test_screen, daemon=True).start(),
        battery_snapshot=battery.snapshot,
        config_path=config_path,
    )
    animator.on_mode_change = apply_mode
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    animator.set_mode("none")
    api.start()
    workers = [
        threading.Thread(target=animator.run, args=(stop,), daemon=True),
        threading.Thread(target=oled.run, args=(stop,), daemon=True),
        threading.Thread(target=battery.run, args=(stop,), daemon=True),
    ]
    for worker in workers:
        worker.start()

    try:
        stop.wait()
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=2)
        api.close()
        audio.stop()
        servos.close()
        oled.close()
        whisplay.set_led(0, 0, 0)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tiny Engineer background hardware and web service")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    return run_service(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
