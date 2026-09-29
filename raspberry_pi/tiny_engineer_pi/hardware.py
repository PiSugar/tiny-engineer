from __future__ import annotations

import math
import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol

from .config import Config, SERVO_NAMES


class Bus(Protocol):
    def write_byte_data(self, address: int, register: int, value: int) -> None: ...
    def read_byte_data(self, address: int, register: int) -> int: ...


class PCA9685:
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, bus: Bus, address: int = 0x40, frequency_hz: int = 50):
        self.bus = bus
        self.address = address
        self.frequency_hz = frequency_hz
        self._last_counts: list[int | None] = [None] * 16
        self._configure()

    def _configure(self) -> None:
        old_mode = self.bus.read_byte_data(self.address, self.MODE1)
        sleep_mode = (old_mode & 0x7F) | 0x10
        prescale = round(25_000_000 / (4096 * self.frequency_hz)) - 1
        self.bus.write_byte_data(self.address, self.MODE1, sleep_mode)
        self.bus.write_byte_data(self.address, self.PRESCALE, prescale)
        # Wake the oscillator even if a previous process left SLEEP asserted.
        # Auto-increment is required for predictable sequential channel writes.
        awake_mode = (old_mode & ~0x10) | 0x20
        self.bus.write_byte_data(self.address, self.MODE1, awake_mode)
        time.sleep(0.005)
        self.bus.write_byte_data(self.address, self.MODE1, awake_mode | 0x80)

    def set_counts(self, channel: int, counts: int) -> None:
        counts = max(0, min(4095, int(counts)))
        if self._last_counts[channel] == counts:
            return
        register = self.LED0_ON_L + 4 * channel
        for offset, value in enumerate((0, 0, counts & 0xFF, counts >> 8)):
            self.bus.write_byte_data(self.address, register + offset, value)
        self._last_counts[channel] = counts

    def full_off(self, channel: int) -> None:
        register = self.LED0_ON_L + 4 * channel
        for offset, value in enumerate((0, 0, 0, 0x10)):
            self.bus.write_byte_data(self.address, register + offset, value)
        self._last_counts[channel] = None


class ServoController:
    """Five-channel smooth servo controller preserving the firmware ordering."""

    COUNT = 5
    MAX_SPEED_DEG_S = 140.0

    def __init__(self, pwm: PCA9685, config: Config):
        self.pwm = pwm
        self.config = config
        self._lock = threading.Lock()
        self._angles = [(lo + hi) / 2 for lo, hi in zip(config.servo_mins, config.servo_maxs)]
        self._targets = self._angles.copy()
        self._speeds = [35.0] * self.COUNT
        self._enabled = False
        self._last_motion = time.monotonic()
        self._servo_mins = list(config.servo_mins)
        self._servo_maxs = list(config.servo_maxs)

    def norm_to_degrees(self, index: int, value: float) -> float:
        value = max(-1.0, min(1.0, float(value)))
        lo, hi = self._servo_mins[index], self._servo_maxs[index]
        return (lo + hi) / 2 + value * (hi - lo) / 2

    def degrees_to_counts(self, degrees: float) -> int:
        degrees = max(0.0, min(180.0, degrees))
        pulse = self.config.servo_min_us + degrees / 180 * (
            self.config.servo_max_us - self.config.servo_min_us
        )
        period_us = 1_000_000 / self.config.servo_frequency_hz
        return round(pulse * 4096 / period_us)

    def set_norm(self, index: int, value: float, speed: float = MAX_SPEED_DEG_S) -> None:
        if not 0 <= index < self.COUNT:
            raise IndexError("servo index must be in 0..4")
        with self._lock:
            self._targets[index] = self.norm_to_degrees(index, value)
            self._speeds[index] = max(1.0, float(speed))
            self._enabled = True

    def set_degrees(self, index: int, degrees: float, speed: float = MAX_SPEED_DEG_S) -> None:
        if not 0 <= index < self.COUNT:
            raise IndexError("servo index must be in 0..4")
        lo, hi = self._servo_mins[index], self._servo_maxs[index]
        with self._lock:
            self._targets[index] = max(lo, min(hi, float(degrees)))
            self._speeds[index] = max(1.0, float(speed))
            self._enabled = True

    def set_electrical_degrees(self, index: int, degrees: float, speed: float = 25.0) -> None:
        """Calibration-only move across the full electrical 0..180 degree range."""
        if not 0 <= index < self.COUNT:
            raise IndexError("servo index must be in 0..4")
        degrees = float(degrees)
        if not 0 <= degrees <= 180:
            raise ValueError("angle must be in 0..180")
        with self._lock:
            self._targets[index] = degrees
            self._speeds[index] = max(1.0, min(self.MAX_SPEED_DEG_S, float(speed)))
            self._enabled = True

    def set_all_electrical_degrees(self, degrees: float, speed: float = 25.0) -> None:
        for index in range(self.COUNT):
            self.set_electrical_degrees(index, degrees, speed)

    def wait_until_still(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if all(abs(target - angle) <= 0.32 for target, angle in zip(self._targets, self._angles)):
                    return True
            time.sleep(0.02)
        return False

    def calibration_ranges(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        with self._lock:
            return tuple(self._servo_mins), tuple(self._servo_maxs)

    def set_calibration_ranges(
        self,
        servo_mins: tuple[float, ...],
        servo_maxs: tuple[float, ...],
    ) -> None:
        if len(servo_mins) != self.COUNT or len(servo_maxs) != self.COUNT:
            raise ValueError("servo ranges must contain five values")
        for minimum, maximum in zip(servo_mins, servo_maxs):
            if not 0 <= minimum < maximum <= 180:
                raise ValueError("servo ranges out of range")
        with self._lock:
            self._servo_mins = list(servo_mins)
            self._servo_maxs = list(servo_maxs)

    def set_pose(self, pose: dict[int, float], speed: float = MAX_SPEED_DEG_S) -> None:
        for index, value in pose.items():
            self.set_norm(index, value, speed)

    def tick(self, elapsed: float) -> bool:
        moving = False
        with self._lock:
            if not self._enabled:
                return False
            for index in range(self.COUNT):
                delta = self._targets[index] - self._angles[index]
                step = self._speeds[index] * elapsed
                if abs(delta) > 0.32:
                    moving = True
                    self._angles[index] += math.copysign(min(abs(delta), step), delta)
                else:
                    self._angles[index] = self._targets[index]
                self.pwm.set_counts(index, self.degrees_to_counts(self._angles[index]))
            if moving:
                self._last_motion = time.monotonic()
            return moving

    def release_if_idle(self) -> None:
        with self._lock:
            if self._enabled and time.monotonic() - self._last_motion >= self.config.release_after_seconds:
                for channel in range(self.COUNT):
                    self.pwm.full_off(channel)
                self._enabled = False

    def snapshot(self) -> list[dict[str, float | str]]:
        with self._lock:
            return [
                {"name": SERVO_NAMES[i], "angle": round(self._angles[i], 1), "target": round(self._targets[i], 1)}
                for i in range(self.COUNT)
            ]

    def close(self) -> None:
        with self._lock:
            for channel in range(self.COUNT):
                self.pwm.full_off(channel)
            self._enabled = False


class AudioDevice:
    def __init__(self, playback_device: str = "default", capture_device: str = "default"):
        self.playback_device = playback_device
        self.capture_device = capture_device
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def play(self, wav_path: str | Path) -> None:
        self.stop()
        with self._lock:
            process = subprocess.Popen(
                ["aplay", "-q", "-D", self.playback_device, str(wav_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._process = process
        threading.Thread(target=self._reap, args=(process,), daemon=True).start()

    def _reap(self, process: subprocess.Popen[bytes]) -> None:
        process.wait()
        with self._lock:
            if self._process is process:
                self._process = None

    def record(self, wav_path: str | Path, seconds: float = 3.0) -> None:
        seconds = max(0.1, min(30.0, float(seconds)))
        try:
            subprocess.run(
                [
                    "arecord", "-q", "-D", self.capture_device, "-f", "S16_LE", "-r", "16000",
                    "-c", "1", "-d", str(math.ceil(seconds)), str(wav_path),
                ],
                check=True,
                timeout=seconds + 5,
            )
        except subprocess.SubprocessError as exc:
            raise OSError(f"Whisplay microphone recording failed: {exc}") from exc

    def stop(self) -> None:
        process = None
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                process = self._process
            self._process = None
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def open_servo_controller(config: Config) -> ServoController:
    from smbus2 import SMBus

    bus = SMBus(config.i2c_bus)
    return ServoController(
        PCA9685(bus, config.pca9685_address, config.servo_frequency_hz),
        config,
    )
