from __future__ import annotations

import logging
import random
import threading
import time
from pathlib import Path

from .hardware import AudioDevice, ServoController


logger = logging.getLogger(__name__)


HEAD, NECK, LEFT, RIGHT, BODY = range(5)
ANIMATIONS = (
    "none", "typing", "reading", "thinking", "ring", "welcome",
    "attention", "error", "abort", "wakeup", "sleep", "dead",
)

LED_COLORS = {
    "none": (0, 8, 20),
    "typing": (0, 90, 255),
    "reading": (0, 180, 140),
    "thinking": (145, 40, 255),
    "ring": (255, 170, 0),
    "welcome": (0, 220, 80),
    "attention": (255, 170, 0),
    "error": (255, 30, 0),
    "abort": (255, 70, 20),
    "wakeup": (30, 150, 255),
    "sleep": (0, 0, 12),
    "dead": (180, 0, 0),
}

REST = {HEAD: 0.0, NECK: 0.0, LEFT: 1.0, RIGHT: -1.0, BODY: 0.0}
SLEEP = {**REST, HEAD: -4 / 7}

# (duration seconds, normalized pose, optional WAV asset)
TIMELINES: dict[str, list[tuple[float, dict[int, float], str | None]]] = {
    "welcome": [
        (0.43, {**REST, RIGHT: 1.0, HEAD: 2 / 7}, "welcome.wav"),
        (1.1, {**REST, RIGHT: 1.0 + 8 / 45, HEAD: 2 / 7 + 3 / 35}, None),
        (1.1, {**REST, RIGHT: 1.0 - 8 / 45, HEAD: 2 / 7 - 3 / 35}, None),
        (0.8, REST, None),
    ],
    "ring": [
        (0.8, {HEAD: 2 / 7, NECK: 0, LEFT: 7 / 9, RIGHT: 1, BODY: -1}, None),
        (0.35, {HEAD: -1, RIGHT: -8 / 9}, "bell.wav"),
        (0.35, {RIGHT: -5 / 9}, None),
        (0.8, REST, None),
    ],
    "attention": [
        (0.5, {HEAD: 6 / 35, NECK: 0, LEFT: 1, RIGHT: 1 / 15, BODY: 0}, "attention.wav"),
        (0.8, {HEAD: 8 / 35, NECK: 4 / 45, RIGHT: 1 / 15}, None),
        (0.8, {HEAD: 4 / 35, NECK: -2 / 15, RIGHT: 1 / 3}, None),
        (0.6, REST, None),
    ],
    "error": [
        (0.65, {HEAD: -12 / 35, NECK: -2 / 9, LEFT: 23 / 45, RIGHT: 13 / 45, BODY: -8 / 45}, "error.wav"),
        (0.55, {HEAD: -9 / 35, NECK: 0}, None),
        (0.55, {HEAD: -14 / 35, NECK: -14 / 45}, None),
        (0.8, REST, None),
    ],
    "abort": [
        (0.55, {HEAD: 16 / 35, NECK: 14 / 45, LEFT: -2 / 9, RIGHT: 1, BODY: -1 / 9}, "abort.wav"),
        (0.65, {HEAD: 12 / 35, LEFT: 2 / 45, RIGHT: 7 / 9}, None),
        (0.65, {HEAD: 1 / 7, NECK: -2 / 15}, None),
        (0.65, REST, None),
    ],
    "wakeup": [(0.01, SLEEP, None), (5.5, REST, None)],
    "sleep": [(2.0, SLEEP, None)],
    "dead": [
        (0.65, {HEAD: -12 / 35, NECK: -2 / 9, LEFT: 23 / 45, RIGHT: 13 / 45, BODY: -8 / 45}, "dead.wav"),
        (1.0, {HEAD: -1, NECK: 0, LEFT: 1, RIGHT: -1, BODY: 0}, None),
    ],
}


class Animator:
    def __init__(self, servos: ServoController, audio: AudioDevice, assets_dir: Path):
        self.servos = servos
        self.audio = audio
        self.assets_dir = assets_dir
        self.mode = "none"
        self.on_mode_change = None
        self._mode_started = time.monotonic()
        self._step_started = self._mode_started
        self._step = 0
        self._next_action = self._mode_started
        self._running = False
        self._lock = threading.Lock()

    def set_mode(self, mode: str) -> None:
        if mode not in ANIMATIONS:
            raise ValueError(f"unknown animation: {mode}")
        with self._lock:
            self.audio.stop()
            self.mode = mode
            self._mode_started = self._step_started = time.monotonic()
            self._step = 0
            self._next_action = self._mode_started
            if mode == "none":
                self.servos.set_pose(REST, 25)
            elif mode in ("typing", "reading", "thinking"):
                self.servos.set_pose(REST, 60)
            else:
                self._apply_timeline_step(mode, 0)
        if self.on_mode_change:
            self.on_mode_change(mode)

    def _apply_timeline_step(self, mode: str, index: int) -> None:
        duration, pose, sound = TIMELINES[mode][index]
        speed = 35 if mode in ("sleep", "wakeup") else 140
        self.servos.set_pose(pose, speed)
        self._step_started = time.monotonic()
        if sound:
            path = self.assets_dir / sound
            if path.exists():
                try:
                    self.audio.play(path)
                except OSError:
                    pass

    def _tick_continuous(self, mode: str, now: float) -> None:
        if now < self._next_action:
            return
        if mode == "typing":
            right = random.choice((True, False))
            index = RIGHT if right else LEFT
            rest = -1 if right else 1
            lift = random.uniform(0.18, 1 / 3)
            self.servos.set_norm(index, rest + lift if right else rest - lift, random.uniform(80, 140))
            self.servos.set_norm(HEAD, random.uniform(-1, -5 / 7), random.uniform(20, 55))
            sway = random.choice((-1, 1)) / 9
            self.servos.set_norm(BODY, sway, 18)
            self.servos.set_norm(NECK, -sway, 18)
            self._next_action = now + random.uniform(0.12, 0.32)
        elif mode == "reading":
            self.servos.set_norm(HEAD, random.uniform(-1, -5 / 7), random.uniform(4, 20))
            self.servos.set_norm(NECK, random.uniform(-2 / 9, 2 / 9), random.uniform(8, 16))
            if random.random() < 0.35:
                self.servos.set_norm(RIGHT, random.uniform(-1, -2 / 3), 120)
            self._next_action = now + random.uniform(0.8, 2.0)
        else:
            poses = ((6 / 7, 0), (27 / 35, -8 / 45), (5 / 7, 8 / 45), (4 / 7, -2 / 9))
            head, neck = random.choice(poses)
            self.servos.set_norm(HEAD, head + random.uniform(-0.06, 0.06), 30)
            self.servos.set_norm(NECK, neck + random.uniform(-0.05, 0.05), 25)
            self._next_action = now + random.uniform(2.2, 4.0)

    def tick(self) -> None:
        now = time.monotonic()
        completed_to_none = False
        with self._lock:
            mode = self.mode
            if mode in ("typing", "reading", "thinking"):
                self._tick_continuous(mode, now)
            elif mode in TIMELINES:
                duration = TIMELINES[mode][self._step][0]
                if now - self._step_started >= duration:
                    self._step += 1
                    if self._step >= len(TIMELINES[mode]):
                        if mode == "dead":
                            self._step = len(TIMELINES[mode]) - 1
                        else:
                            self.mode = "none"
                            self.servos.set_pose(REST, 25)
                            completed_to_none = True
                    else:
                        self._apply_timeline_step(mode, self._step)
        if completed_to_none and self.on_mode_change:
            self.on_mode_change("none")

    def run(self, stop_event: threading.Event) -> None:
        self._running = True
        previous = time.monotonic()
        i2c_failures = 0
        while not stop_event.is_set():
            now = time.monotonic()
            try:
                self.tick()
                moving = self.servos.tick(now - previous)
                if self.mode == "none" and not moving:
                    self.servos.release_if_idle()
                if i2c_failures:
                    logger.warning("PCA9685 I2C communication recovered")
                    i2c_failures = 0
            except OSError as exc:
                i2c_failures += 1
                if i2c_failures == 1 or i2c_failures % 50 == 0:
                    logger.warning(
                        "PCA9685 I2C error; servo loop will keep retrying: %s", exc
                    )
            previous = now
            stop_event.wait(0.1 if i2c_failures else 0.02)
        self._running = False
