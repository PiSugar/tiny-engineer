from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from tiny_engineer_pi.config import Config, SERVO_NAMES, load_config, save_servo_ranges
from tiny_engineer_pi.hardware import PCA9685, ServoController
from tiny_engineer_pi.http_api import ApiServer, load_original_index


class FakeBus:
    def __init__(self):
        self.writes = []

    def read_byte_data(self, address, register):
        return 0

    def write_byte_data(self, address, register, value):
        self.writes.append((address, register, value))


class RuntimeTests(unittest.TestCase):
    repo_root = Path(__file__).resolve().parents[2]

    def test_servo_order_matches_firmware(self):
        self.assertEqual(SERVO_NAMES, ("head", "neck", "hand_left", "hand_right", "body"))

    def test_norm_mapping_uses_original_ranges(self):
        controller = ServoController(PCA9685(FakeBus()), Config())
        self.assertEqual(controller.norm_to_degrees(0, -1), 60)
        self.assertEqual(controller.norm_to_degrees(0, 0), 95)
        self.assertEqual(controller.norm_to_degrees(0, 1), 130)
        self.assertEqual(controller.norm_to_degrees(3, -1), 35)
        self.assertEqual(controller.norm_to_degrees(3, 1), 125)

    def test_pwm_conversion_matches_800_to_2200_us(self):
        controller = ServoController(PCA9685(FakeBus()), Config())
        self.assertEqual(controller.degrees_to_counts(0), round(800 * 4096 / 20000))
        self.assertEqual(controller.degrees_to_counts(180), round(2200 * 4096 / 20000))

    def test_pca9685_initialization_clears_stale_sleep_bit(self):
        bus = FakeBus()
        bus.read_byte_data = lambda _address, _register: 0x31
        PCA9685(bus)
        mode_writes = [value for _, register, value in bus.writes if register == PCA9685.MODE1]
        self.assertEqual(mode_writes[-2] & 0x10, 0)
        self.assertEqual(mode_writes[-1] & 0x10, 0)

    def test_config_rejects_bad_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"servo_mins": [90] * 5, "servo_maxs": [80] * 5}))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_audio_defaults_use_shared_pipewire_pulse_device(self):
        config = Config()
        self.assertEqual(config.alsa_playback_device, "pulse")
        self.assertEqual(config.alsa_capture_device, "pulse")

        runner = (self.repo_root / "raspberry_pi/run_service.sh").read_text()
        self.assertIn('XDG_RUNTIME_DIR="/run/user/$(id -u)"', runner)

    def test_release_writes_full_off(self):
        bus = FakeBus()
        config = Config(release_after_seconds=0)
        controller = ServoController(PCA9685(bus), config)
        controller.set_norm(0, 0)
        controller.tick(0.02)
        before = len(bus.writes)
        controller.release_if_idle()
        full_off_writes = bus.writes[before:]
        self.assertEqual(len(full_off_writes), 20)
        self.assertEqual(sum(value == 0x10 for _, _, value in full_off_writes), 5)

    def test_calibration_move_bypasses_saved_safe_range(self):
        controller = ServoController(PCA9685(FakeBus()), Config())
        controller.set_electrical_degrees(0, 20)
        self.assertEqual(controller.snapshot()[0]["target"], 20)
        controller.set_degrees(0, 20)
        self.assertEqual(controller.snapshot()[0]["target"], 60)

    def test_servo_calibration_ranges_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"port": 8080}))
            save_servo_ranges(path, (61, 41, 46, 36, 41), (129, 129, 134, 124, 129))
            loaded = load_config(path)
            self.assertEqual(loaded.servo_mins, (61, 41, 46, 36, 41))
            self.assertEqual(loaded.servo_maxs, (129, 129, 134, 124, 129))

    def test_http_animation_compatibility(self):
        class FakeAnimator:
            mode = "none"
            assets_dir = RuntimeTests.repo_root / "assets"

            def set_mode(self, mode):
                if mode not in ("none", "typing"):
                    raise ValueError("unknown animation")
                self.mode = mode

        class FakeServos:
            def snapshot(self):
                return []

            def calibration_ranges(self):
                return Config().servo_mins, Config().servo_maxs

        animator = FakeAnimator()
        try:
            server = ApiServer("127.0.0.1", 0, animator, FakeServos(), object(), Config())
        except PermissionError:
            self.skipTest("sandbox does not permit local sockets")
        server.start()
        port = server.httpd.server_address[1]
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/anim?name=typing", method="POST"
            )
            with urllib.request.urlopen(request) as response:
                body = json.load(response)
            self.assertEqual(body, {"ok": True, "animation": "typing"})
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/anim") as response:
                self.assertEqual(json.load(response)["animation"], "typing")
        finally:
            server.close()

    def test_web_ui_is_loaded_from_original_firmware_source(self):
        html = load_original_index(self.repo_root)
        self.assertIn('<section id="view-animations" class="view">', html)
        self.assertIn('A desk robot that acts out your AI coding assistant', html)
        self.assertIn('href="/calibration"', html)
        self.assertIn('piCalibrationMode', html)
        self.assertIn(
            "body.pi-calibration:not(.setup-mode) #setup-wizard{display:block!important}",
            html,
        )
        source = (self.repo_root / "src/http/index_page.cpp").read_text()
        self.assertNotIn('href="/calibration"', source)

    def test_whisplay_app_is_only_an_http_client(self):
        app_source = (self.repo_root / "raspberry_pi/tiny_engineer_pi/app.py").read_text()
        self.assertIn("class RobotServiceClient", app_source)
        self.assertNotIn("open_servo_controller", app_source)
        self.assertNotIn("EyeDisplay", app_source)
        self.assertNotIn("ApiServer", app_source)

    def test_background_service_owns_hardware_and_web(self):
        service_source = (self.repo_root / "raspberry_pi/tiny_engineer_pi/service.py").read_text()
        self.assertIn("open_servo_controller", service_source)
        self.assertIn("EyeDisplay", service_source)
        self.assertIn("ApiServer", service_source)
        unit = (self.repo_root / "raspberry_pi/tiny-engineer.service.in").read_text()
        self.assertIn("ExecStart=@ROOT@/raspberry_pi/run_service.sh", unit)
        self.assertIn("Restart=on-failure", unit)

    def test_classic_eye_renderer_accepts_original_blink_heights(self):
        try:
            from PIL import Image, ImageDraw
            from tiny_engineer_pi.oled import Eye, OriginalEyes
        except ImportError:
            self.skipTest("Pillow is not installed on this host")

        for height in range(15):
            image = Image.new("1", (128, 32))
            OriginalEyes._draw_eye(ImageDraw.Draw(image), Eye(20, 9, 24, height))


if __name__ == "__main__":
    unittest.main()
