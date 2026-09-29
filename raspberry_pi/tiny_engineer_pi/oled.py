from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from PIL import Image, ImageDraw


@dataclass
class Eye:
    x: int
    y: int
    width: int
    height: int


DEFAULT_LEFT = Eye(20, 9, 24, 14)
DEFAULT_RIGHT = Eye(84, 9, 24, 14)
EYE_CENTER_Y = 16
BLINK_CLOSED_AMOUNT = 0.12


def cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def lerp_int(start: int, end: int, t: float) -> int:
    return int(start + (end - start) * t)


def eye_with_height(x: int, width: int, height: int) -> Eye:
    return Eye(x, EYE_CENTER_Y - height // 2, width, height)


def render_eye(base: Eye, open_amount: float) -> Eye:
    height = int(base.height * open_amount)
    if height <= 0:
        return Eye(base.x, base.y, base.width, 0)
    return Eye(base.x, base.y + (base.height - height) // 2, base.width, height)


class OriginalEyes:
    """Port of src/display/eyes classic renderer and mode state machine."""

    def __init__(self, servo_angles: Callable[[], list[dict]] | None = None):
        self.servo_angles = servo_angles
        self.mode = "none"
        self.started = time.monotonic()
        self.left = DEFAULT_LEFT
        self.right = DEFAULT_RIGHT
        self.open_amount = 1.0
        self.blink_phase = "idle"
        self.phase_started = self.started
        self.phase_duration = 0.0
        self.next_blink = self.started + random.uniform(0.8, 2.0)
        self.blinks_total = 1
        self.blinks_done = 0
        self.state: dict[str, Any] = {}
        self.set_mode("none")

    def set_mode(self, mode: str) -> None:
        now = time.monotonic()
        self.mode = mode
        self.started = now
        self.left = DEFAULT_LEFT
        self.right = DEFAULT_RIGHT
        self.state = {}
        if mode == "welcome":
            self._reset_blink(now, 10.0)
        elif mode == "attention":
            self._reset_blink(now, 1.2)
        elif mode == "error":
            self._reset_blink(now, 2.3)
        elif mode == "abort":
            self._reset_blink(now, 1.5)
        elif mode == "wakeup":
            self._reset_blink(now, 60.0, BLINK_CLOSED_AMOUNT)
            self.state.update(blink1=True, blink2=True)
        elif mode == "dead":
            self.open_amount = 1.0
            self.state.update(next_flicker=now, blank_until=0.0, left_h=9, right_h=11)
        elif mode == "sleep":
            self.state["sleep_from"] = self.open_amount
        else:
            self._reset_blink(now, random.uniform(0.8, 2.0))

        if mode == "none":
            self.state["next_gaze"] = now + random.uniform(4, 8)
            self.state.update(gx=0, gy=0, from_x=0, from_y=0, target_x=0, target_y=0)
        elif mode == "typing":
            self.state["look_right"] = random.random() < 0.5
            self.state["next_flip"] = now + random.uniform(0.12, 0.26)
        elif mode == "reading":
            self.state.update(scan_phase="forward", scan=-3, scan_start=now, scan_duration=random.uniform(0.9, 1.5))
        elif mode == "thinking":
            self.state.update(side=3 if random.random() < 0.5 else -3, squint_left=random.random() < 0.5,
                              next_flip=now + random.uniform(2, 4.5), next_idea=now + random.uniform(5, 10), idea_until=0.0)
        elif mode == "error":
            self.state.update(next_scan=now + 0.46, look=0, tense=True)
        elif mode == "ring":
            self.state.update(
                impact_x=random.randint(-2, 2),
                impact_y=random.randint(-2, 2),
                impact_duration=random.uniform(0.18, 0.26),
            )

    def _reset_blink(self, now: float, delay: float, amount: float = 1.0) -> None:
        self.blink_phase = "idle"
        self.open_amount = amount
        self.next_blink = now + delay
        self.blinks_total = 1
        self.blinks_done = 0

    def _begin_blink_phase(self, phase: str, now: float, lo: float, hi: float) -> None:
        self.blink_phase = phase
        self.phase_started = now
        self.phase_duration = random.uniform(lo, hi)

    def _blink(self, now: float) -> None:
        if self.blink_phase == "idle":
            if now >= self.next_blink:
                self.blinks_total = 2 if random.randrange(100) < 22 else 1
                self.blinks_done = 0
                self._begin_blink_phase("closing", now, 0.065, 0.120)
            return
        progress = min(1.0, (now - self.phase_started) / self.phase_duration)
        if self.blink_phase == "closing":
            self.open_amount = 1 - cubic(progress) * (1 - BLINK_CLOSED_AMOUNT)
            if progress >= 1:
                self.open_amount = BLINK_CLOSED_AMOUNT
                self._begin_blink_phase("closed", now, 0.035, 0.090)
        elif self.blink_phase == "closed" and progress >= 1:
            self._begin_blink_phase("opening", now, 0.075, 0.130)
        elif self.blink_phase == "opening":
            self.open_amount = BLINK_CLOSED_AMOUNT + cubic(progress) * (1 - BLINK_CLOSED_AMOUNT)
            if progress >= 1:
                self.open_amount = 1.0
                self.blinks_done += 1
                self.blink_phase = "idle"
                if self.blinks_done < self.blinks_total:
                    self.next_blink = now + random.uniform(0.09, 0.22)
                else:
                    self.next_blink = now + (random.uniform(1.8, 4.0) if self.mode == "typing" else random.uniform(2.5, 5.5))

    def _pose_idle(self, now: float) -> None:
        s = self.state
        if now >= s["next_gaze"]:
            s.update(from_x=s["gx"], from_y=s["gy"], target_x=random.randint(-2, 2), target_y=random.randint(-1, 1),
                     move_start=now, move_duration=random.uniform(0.3, 0.4), next_gaze=now + random.uniform(4, 8))
        if "move_start" in s:
            t = cubic(min(1.0, (now - s["move_start"]) / s["move_duration"]))
            s["gx"] = lerp_int(s["from_x"], s["target_x"], t)
            s["gy"] = lerp_int(s["from_y"], s["target_y"], t)
        self.left = Eye(20 + s["gx"], 9 + s["gy"], 24, 14)
        self.right = Eye(84 + s["gx"], 9 + s["gy"], 24, 14)

    def _pose_typing(self, now: float) -> None:
        if now >= self.state["next_flip"]:
            self.state["look_right"] = not self.state["look_right"]
            self.state["next_flip"] = now + random.uniform(0.12, 0.26)
        x = 2 if self.state["look_right"] else -2
        self.left = eye_with_height(20 + x, 24, 12)
        self.right = eye_with_height(84 + x, 24, 12)
        self.left.y += 2
        self.right.y += 2

    def _servo_norm(self, index: int, lo: float, hi: float) -> float:
        if not self.servo_angles:
            return 0.0
        angle = float(self.servo_angles()[index]["angle"])
        return max(-1.0, min(1.0, 2 * (angle - lo) / (hi - lo) - 1))

    def _pose_reading(self, now: float) -> None:
        s = self.state
        t = cubic(min(1.0, (now - s["scan_start"]) / s["scan_duration"]))
        if s["scan_phase"] == "forward":
            s["scan"] = lerp_int(-3, 3, t)
            if t >= 1:
                s.update(scan_phase="return", scan_start=now, scan_duration=random.uniform(0.07, 0.14))
        else:
            s["scan"] = lerp_int(3, -3, t)
            if t >= 1:
                s.update(scan_phase="forward", scan_start=now, scan_duration=random.uniform(0.9, 1.5))
                if self.blink_phase == "idle":
                    self.next_blink = now + random.uniform(0.08, 0.18)
        neck = self._servo_norm(1, 40, 130)
        head = self._servo_norm(0, 60, 130)
        gaze_x = int(max(-1, min(1, neck / (2 / 9))) * 6) + s["scan"]
        head_band = max(-1, min(1, (head + 1) / (2 / 7)))
        gaze_y = lerp_int(3, 1, head_band)
        self.left = eye_with_height(20 + gaze_x, 24, 14)
        self.right = eye_with_height(84 + gaze_x, 24, 14)
        self.left.y += gaze_y
        self.right.y += gaze_y

    def _pose_thinking(self, now: float) -> None:
        s = self.state
        if now >= s["next_flip"]:
            s["squint_left"] = not s["squint_left"]
            s["side"] *= -1
            s["next_flip"] = now + random.uniform(2, 4.5)
        if now >= s["next_idea"] and not s["idea_until"]:
            s["idea_until"] = now + 0.18
            s["next_idea"] = now + random.uniform(5, 10)
        idea = bool(s["idea_until"] and now < s["idea_until"])
        if s["idea_until"] and not idea:
            s["idea_until"] = 0.0
        lh, rh = (17, 17) if idea else ((11, 14) if s["squint_left"] else (14, 11))
        self.left = eye_with_height(20 + s["side"], 24, lh)
        self.right = eye_with_height(84 + s["side"], 24, rh)
        self.left.y -= 2
        self.right.y -= 2

    def _fixed_pose(self, elapsed: float) -> None:
        x = y = 0
        lh = rh = 14
        if self.mode == "ring":
            lh = rh = 9
            impact_elapsed = elapsed - 0.8
            if 0 <= impact_elapsed < self.state["impact_duration"]:
                lh = rh = 18
                x = self.state["impact_x"]
                y = self.state["impact_y"]
        elif self.mode == "welcome":
            if elapsed < 0.8:
                lh = rh = 16; y = -2
            elif elapsed < 1.34:
                lh = rh = 16; y = -2
                if 1.02 <= elapsed < 1.12:
                    raw = (elapsed - 1.02) / 0.05 if elapsed < 1.07 else (1.12 - elapsed) / 0.05
                    lh = rh = int(2 + 14 * cubic(raw))
            elif elapsed < 2.4:
                lh = rh = 12
            elif elapsed < 2.68:
                lh, rh = 17, 15
        elif self.mode == "attention":
            lh = rh = 16; y = -2
            if elapsed < 0.64:
                lh = rh = 15
            elif elapsed < 1.54:
                if 0.72 <= elapsed < 0.78:
                    raw = (elapsed - 0.72) / 0.03 if elapsed < 0.75 else (0.78 - elapsed) / 0.03
                    lh = rh = int(2 + 14 * cubic(raw))
                elif elapsed >= 0.78:
                    lh, rh = 17, 15
            elif elapsed < 2.96:
                x, y, lh, rh = 5, -1, 12, 13
        elif self.mode == "abort":
            if elapsed < 0.52:
                y, lh, rh = -3, 17, 17
            elif elapsed < 1.35:
                x, y, lh, rh = 5, -1, 11, 15
            elif elapsed < 2.05:
                x, y, lh, rh = -4, 0, 13, 10
            elif elapsed < 2.5:
                x, y, lh, rh = 3, -2, 10, 14
            if 1.18 <= elapsed < 1.32:
                raw = (elapsed - 1.18) / 0.07 if elapsed < 1.25 else (1.32 - elapsed) / 0.07
                lh = rh = int(16 - 12 * cubic(raw))
        self.left = eye_with_height(20 + x, 24, lh)
        self.right = eye_with_height(84 + x, 24, rh)
        self.left.y += y
        self.right.y += y

    @staticmethod
    def _error_look(look: int, tense: bool) -> tuple[int, int, int]:
        if look == 0:
            return -5, 10 if tense else 11, 15
        if look == 1:
            return 5, 12 if tense else 13, 13 if tense else 14
        return -1, 11 if tense else 12, 14 if tense else 15

    def _pose_error(self, now: float, elapsed: float) -> None:
        if elapsed < 0.46: look, tense = 0, True
        elif elapsed < 1.06: look, tense = 1, False
        elif elapsed < 2.14:
            look = int(((elapsed - 1.06) / 0.36) % 3); tense = look != 1
        elif elapsed < 2.22: look, tense = 2, True
        else:
            if now >= self.state["next_scan"]:
                self.state["look"] = (self.state["look"] + 1) % 3
                self.state["tense"] = not self.state["tense"]
                self.state["next_scan"] = now + random.uniform(0.36, 0.82)
            look, tense = self.state["look"], self.state["tense"]
        x, lh, rh = self._error_look(look, tense)
        self.left = eye_with_height(20 + x, 24, lh); self.left.y += 1
        self.right = eye_with_height(84 + x, 24, rh); self.right.y -= 1

    def _pose_dead(self, now: float, elapsed: float) -> bool:
        if elapsed >= 2.2:
            self.left, self.right = DEFAULT_LEFT, DEFAULT_RIGHT
            return True
        s = self.state
        if elapsed >= 2.0:
            lh = rh = 2
        elif elapsed >= 1.7:
            t = cubic((elapsed - 1.7) / 0.3)
            lh = int(s["left_h"] + (2 - s["left_h"]) * t + 0.5)
            rh = int(s["right_h"] + (2 - s["right_h"]) * t + 0.5)
        else:
            dense = elapsed >= 1.4
            if now < s["blank_until"]:
                s["left_h"] = s["right_h"] = 1
            elif now >= s["next_flicker"]:
                s["left_h"] = max(3, min(14, 9 + random.randint(-3, 3)))
                s["right_h"] = max(3, min(14, 11 + random.randint(-3, 3)))
                if random.randrange(100) < (22 if dense else 10):
                    s["blank_until"] = now + random.uniform(0.03, 0.08)
                    s["left_h"] = s["right_h"] = 1
                s["next_flicker"] = now + (random.uniform(0.028, 0.07) if dense else random.uniform(0.04, 0.12))
            lh, rh = s["left_h"], s["right_h"]
        self.left = eye_with_height(20, 24, lh); self.left.y += 1
        self.right = eye_with_height(84, 24, rh); self.right.y += 1
        return False

    def _pose_wakeup(self, now: float, elapsed: float) -> None:
        self.left, self.right = DEFAULT_LEFT, DEFAULT_RIGHT
        if elapsed < 2:
            self.open_amount = BLINK_CLOSED_AMOUNT + cubic(elapsed / 2) * (1 - BLINK_CLOSED_AMOUNT)
        else:
            self.open_amount = 1.0 if self.blink_phase == "idle" else self.open_amount
            if self.state["blink1"] and elapsed >= 2.4:
                self.next_blink = now; self.state["blink1"] = False
            if self.state["blink2"] and elapsed >= 3.8:
                self.next_blink = now; self.state["blink2"] = False
            self._blink(now)

    def _pose_sleep(self, elapsed: float) -> None:
        start = self.state["sleep_from"]
        if elapsed < 0.7:
            self.open_amount = start + (0.15 - start) * cubic(elapsed / 0.7)
        elif elapsed < 1.1:
            self.open_amount = 0.15 + 0.35 * cubic((elapsed - 0.7) / 0.4)
        elif elapsed < 2.0:
            t = 1 - (1 - ((elapsed - 1.1) / 0.9)) ** 3
            self.open_amount = 0.5 * (1 - t)
        else:
            self.open_amount = 0.0
        self.left, self.right = DEFAULT_LEFT, DEFAULT_RIGHT

    def render(self) -> Image.Image:
        now = time.monotonic()
        elapsed = now - self.started
        dead_x = False
        if self.mode == "none": self._pose_idle(now)
        elif self.mode == "typing": self._pose_typing(now)
        elif self.mode == "reading": self._pose_reading(now)
        elif self.mode == "thinking": self._pose_thinking(now)
        elif self.mode in ("ring", "welcome", "attention", "abort"): self._fixed_pose(elapsed)
        elif self.mode == "error": self._pose_error(now, elapsed)
        elif self.mode == "dead": dead_x = self._pose_dead(now, elapsed)
        elif self.mode == "wakeup": self._pose_wakeup(now, elapsed)
        elif self.mode == "sleep": self._pose_sleep(elapsed)
        if self.mode not in ("welcome", "wakeup", "dead", "sleep"):
            self._blink(now)
        image = Image.new("1", (128, 32))
        draw = ImageDraw.Draw(image)
        if dead_x:
            self._draw_x(draw, self.left); self._draw_x(draw, self.right)
        else:
            self._draw_eye(draw, render_eye(self.left, self.open_amount))
            self._draw_eye(draw, render_eye(self.right, self.open_amount))
        return image

    @staticmethod
    def _draw_eye(draw: ImageDraw.ImageDraw, eye: Eye) -> None:
        if eye.width <= 0 or eye.height <= 0:
            return
        radius = min(3, eye.width // 2, eye.height // 2)
        if radius <= 0:
            draw.rectangle((eye.x, eye.y, eye.x + eye.width - 1, eye.y + eye.height - 1), fill=1)
            return
        horizontal = (eye.x + radius, eye.y, eye.x + eye.width - radius - 1, eye.y + eye.height - 1)
        vertical = (eye.x, eye.y + radius, eye.x + eye.width - 1, eye.y + eye.height - radius - 1)
        # Arduino fillRect treats a zero-height center strip as a no-op. Pillow
        # rejects the equivalent inverted box, so skip only that degenerate
        # primitive while retaining the original circles and pixel geometry.
        if horizontal[2] >= horizontal[0] and horizontal[3] >= horizontal[1]:
            draw.rectangle(horizontal, fill=1)
        if vertical[2] >= vertical[0] and vertical[3] >= vertical[1]:
            draw.rectangle(vertical, fill=1)
        for cx in (eye.x + radius, eye.x + eye.width - radius - 1):
            for cy in (eye.y + radius, eye.y + eye.height - radius - 1):
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=1)

    @staticmethod
    def _draw_x(draw: ImageDraw.ImageDraw, eye: Eye) -> None:
        x0, y0 = eye.x + 3, eye.y + 2
        x1, y1 = eye.x + eye.width - 4, eye.y + eye.height - 3
        for offset in (-1, 0, 1):
            draw.line((x0 + offset, y0, x1 + offset, y1), fill=1)
            draw.line((x0, y0 + offset, x1, y1 + offset), fill=1)
            draw.line((x1 + offset, y0, x0 + offset, y1), fill=1)
            draw.line((x1, y0 + offset, x0, y1 + offset), fill=1)


class EyeDisplay:
    def __init__(self, i2c_bus: int, address: int, rotate_180: bool = False,
                 servo_angles: Callable[[], list[dict]] | None = None):
        self.device: Any | None = None
        self.rotate_180 = rotate_180
        self.renderer = OriginalEyes(servo_angles)
        self._lock = threading.Lock()
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            self.device = ssd1306(i2c(port=i2c_bus, address=address), width=128, height=32)
        except (ImportError, OSError):
            self.device = None

    @property
    def connected(self) -> bool:
        return self.device is not None

    def show_mode(self, mode: str) -> None:
        with self._lock:
            self.renderer.set_mode(mode)

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            if self.device is not None:
                with self._lock:
                    image = self.renderer.render()
                    if self.rotate_180:
                        image = image.rotate(180)
                    self.device.display(image)
            stop_event.wait(0.033)

    def close(self) -> None:
        if self.device is not None:
            self.device.cleanup()
