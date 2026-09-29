from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


SERVO_NAMES = ("head", "neck", "hand_left", "hand_right", "body")


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    i2c_bus: int = 1
    pca9685_address: int = 0x40
    oled_address: int = 0x3C
    oled_rotate_180: bool = False
    # Go through PipeWire/PulseAudio so the background service never owns the
    # Whisplay hardware PCM directly. Other apps can play and record at the
    # same time; the audio server performs the mixing and source fan-out.
    alsa_playback_device: str = "pulse"
    alsa_capture_device: str = "pulse"
    servo_mins: tuple[float, ...] = (60, 40, 45, 35, 40)
    servo_maxs: tuple[float, ...] = (130, 130, 135, 125, 130)
    servo_frequency_hz: int = 50
    servo_min_us: int = 800
    servo_max_us: int = 2200
    release_after_seconds: float = 2.0

    def validate(self) -> "Config":
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be in 1..65535")
        if len(self.servo_mins) != 5 or len(self.servo_maxs) != 5:
            raise ValueError("servo_mins and servo_maxs must contain five values")
        for index, (minimum, maximum) in enumerate(zip(self.servo_mins, self.servo_maxs)):
            if not 0 <= minimum < maximum <= 180:
                raise ValueError(f"invalid range for {SERVO_NAMES[index]}")
        if not 40 <= self.servo_frequency_hz <= 100:
            raise ValueError("servo_frequency_hz must be in 40..100")
        if not 100 <= self.servo_min_us < self.servo_max_us <= 3000:
            raise ValueError("invalid servo pulse range")
        return self


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    config_path = Path(path)
    if not config_path.exists():
        return Config()
    raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(Config)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(unknown)}")
    if "servo_mins" in raw:
        raw["servo_mins"] = tuple(float(value) for value in raw["servo_mins"])
    if "servo_maxs" in raw:
        raw["servo_maxs"] = tuple(float(value) for value in raw["servo_maxs"])
    return Config(**raw).validate()


def save_servo_ranges(
    path: str | Path,
    servo_mins: tuple[float, ...],
    servo_maxs: tuple[float, ...],
) -> None:
    """Persist only calibration fields while preserving all other settings."""
    config_path = Path(path)
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["servo_mins"] = list(servo_mins)
    raw["servo_maxs"] = list(servo_maxs)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_path)
