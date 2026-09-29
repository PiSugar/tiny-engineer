from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .animation import Animator
from .config import Config, save_servo_ranges
from .hardware import AudioDevice, ServoController


WEB_PATHS = {"/", "/animations", "/tests", "/servo", "/calibration", "/config", "/api"}


def load_original_index(repo_root: Path) -> str:
    """Load the original UI and add the Pi-only calibration entry."""
    source = (repo_root / "src" / "http" / "index_page.cpp").read_text(encoding="utf-8")
    start_marker = 'R"html('
    end_marker = ')html";'
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker, start)
    html = source[start:end]
    html = html.replace(
        '<a href="/servo" data-nav="/servo">Servo</a>',
        '<a href="/servo" data-nav="/servo">Servo</a>\n<a href="/calibration" data-nav="/calibration">Calibration</a>',
        1,
    )
    html = html.replace(
        '<a class="card" href="/servo"><h3>Servo control</h3><p>Move individual servos to any angle.</p></a>',
        '<a class="card" href="/servo"><h3>Servo control</h3><p>Move individual servos to any angle.</p></a>\n'
        '<a class="card" href="/calibration"><h3>Servo calibration</h3><p>Attach horns at 90&deg;, then find and save each joint\'s safe range.</p></a>',
        1,
    )
    html = html.replace(
        "</style>",
        "body.pi-calibration:not(.setup-mode) #setup-wizard{display:block!important}"
        "body.pi-calibration #config-form,body.pi-calibration .config-danger,body.pi-calibration #config-page-desc{display:none!important}"
        "</style>",
        1,
    )
    html = html.replace(
        "var provisioningMode=false;",
        "var provisioningMode=false;\nvar piCalibrationMode=false;",
        1,
    )
    html = html.replace(
        'var map={"/":"view-home","/animations":"view-animations","/servo":"view-servo","/tests":"view-tests","/config":"view-config","/api":"view-api"};',
        'piCalibrationMode=path==="/calibration";\n'
        '  document.body.classList.toggle("pi-calibration",piCalibrationMode);\n'
        '  if(piCalibrationMode){resetSetupWizard();document.getElementById("config-page-title").textContent="Servo calibration";}\n'
        '  var map={"/":"view-home","/animations":"view-animations","/servo":"view-servo","/calibration":"view-config","/tests":"view-tests","/config":"view-config","/api":"view-api"};',
        1,
    )
    html = html.replace(
        'document.getElementById("setup-next").textContent=nextLabel[id]||"Next";',
        'document.getElementById("setup-next").textContent=(piCalibrationMode&&id==="servos")?"Save calibration":(nextLabel[id]||"Next");',
        1,
    )
    html = html.replace(
        '        setSetupStep("oled");\n        enterSetupOledStep();',
        '        if(piCalibrationMode){\n'
        '          setStatus("Servo calibration saved.","ok");\n'
        '          setTimeout(function(){location.href="/servo";},700);\n'
        '          return;\n'
        '        }\n'
        '        setSetupStep("oled");\n        enterSetupOledStep();',
        1,
    )
    return html


def memory_info() -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return 0, 0
    return values.get("MemAvailable", 0), values.get("MemTotal", 0)


def cpu_temperature() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return None


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


class ApiServer:
    def __init__(
        self,
        host: str,
        port: int,
        animator: Animator,
        servos: ServoController,
        audio: AudioDevice,
        config: Config,
        test_led=None,
        test_screen=None,
        battery_snapshot=None,
        config_path: str | Path | None = None,
    ):
        self.started = time.monotonic()
        self.animator = animator
        self.servos = servos
        self.audio = audio
        self.config = config
        self.test_led = test_led
        self.test_screen = test_screen
        self.battery_snapshot = battery_snapshot or (lambda: (-1, False))
        self.config_path = Path(config_path) if config_path else None
        self.index_html = load_original_index(animator.assets_dir.parent).encode()
        self._recording_dir = Path(tempfile.gettempdir()) / "tiny-engineer"
        self._recording_dir.mkdir(exist_ok=True)
        outer = self

        def settings_json() -> dict:
            servo_mins, servo_maxs = outer.servos.calibration_ranges()
            return {
                "ok": True,
                "sleep_timeout": 10,
                "hostname": socket.gethostname(),
                "volume": 70,
                "welcome": True,
                "serial_log": False,
                "continuous_timeout": 5,
                "loading": "progress",
                "eyes_style": "classic",
                "access_token_set": False,
                "wifi_configured": True,
                "wifi_ssid": "",
                "wifi_password_set": True,
                "servo_mins": list(servo_mins),
                "servo_maxs": list(servo_maxs),
                "rgb_order": "RGB",
                "oled_rotate_180": config.oled_rotate_180,
            }

        class Handler(BaseHTTPRequestHandler):
            def _json(self, status: int, body: dict) -> None:
                data = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def _html(self) -> None:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(outer.index_html)))
                self.end_headers()
                self.wfile.write(outer.index_html)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path in WEB_PATHS:
                    self._html()
                elif parsed.path == "/auth":
                    self._json(HTTPStatus.OK, {
                        "ok": True, "required": False, "wifi_configured": True, "provisioning": False,
                    })
                elif parsed.path == "/health":
                    free_memory, total_memory = memory_info()
                    ip = local_ip()
                    level, charging = outer.battery_snapshot()
                    body = {
                        "ok": True,
                        "platform": "raspberry-pi-zero-2w",
                        "uptime_ms": round((time.monotonic() - outer.started) * 1000),
                        "free_heap": free_memory,
                        "heap_size": total_memory,
                        "cpu_temp_c": cpu_temperature(),
                        "wifi": {"connected": bool(ip), "ip": ip, "rssi": 0, "hostname": socket.gethostname() + ".local"},
                        "wifi_configured": True,
                        "provisioning": False,
                        "setup_ap_ssid": "",
                        "setup_ap_ip": "",
                        "oled": True,
                        "animation": outer.animator.mode,
                        "servos": outer.servos.snapshot(),
                        "battery": {"level": level, "charging": charging},
                    }
                    self._json(HTTPStatus.OK, body)
                elif parsed.path == "/settings":
                    self._json(HTTPStatus.OK, settings_json())
                elif parsed.path == "/anim":
                    self._json(HTTPStatus.OK, {"ok": True, "animation": outer.animator.mode})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                try:
                    if parsed.path == "/anim":
                        name = params.get("name", [""])[0]
                        if not name:
                            raise ValueError("missing name")
                        outer.animator.set_mode(name)
                        self._json(HTTPStatus.OK, {"ok": True, "animation": name})
                    elif parsed.path == "/test/servo":
                        index = int(params.get("index", [""])[0])
                        angle = float(params.get("angle", [""])[0])
                        outer.servos.set_degrees(index, angle)
                        self._json(HTTPStatus.OK, {"ok": True, "index": index, "angle": angle})
                    elif parsed.path == "/setup/servo":
                        outer.animator.set_mode("none")
                        if "all" in params:
                            if params["all"][0] != "90":
                                raise ValueError("invalid all")
                            outer.servos.set_all_electrical_degrees(90, 25)
                            if not outer.servos.wait_until_still(10):
                                raise OSError("servo calibration move timed out")
                            self._json(HTTPStatus.OK, {"ok": True, "setup": "servo", "all": 90})
                        else:
                            if "index" not in params or "angle" not in params:
                                raise ValueError("missing index or angle")
                            index = int(params["index"][0])
                            angle = float(params["angle"][0])
                            outer.servos.set_electrical_degrees(index, angle, 25)
                            if not outer.servos.wait_until_still(10):
                                raise OSError("servo calibration move timed out")
                            self._json(HTTPStatus.OK, {
                                "ok": True, "setup": "servo", "index": index, "angle": angle,
                            })
                    elif parsed.path in ("/test/audio", "/test/audio/bell", "/setup/audio"):
                        mode = params.get("mode", ["play"])[0]
                        if mode == "record":
                            seconds = float(params.get("seconds", ["3"])[0])
                            destination = outer._recording_dir / "microphone-test.wav"
                            outer.audio.record(destination, seconds)
                            self._json(HTTPStatus.OK, {"ok": True, "mode": "record", "path": str(destination)})
                        else:
                            outer.audio.play(outer.animator.assets_dir / "bell.wav")
                            self._json(HTTPStatus.OK, {"ok": True, "mode": "play"})
                    elif parsed.path == "/test/screen":
                        if outer.test_screen:
                            outer.test_screen()
                        self._json(HTTPStatus.OK, {"ok": True})
                    elif parsed.path == "/test/led":
                        if outer.test_led:
                            threading.Thread(target=outer.test_led, daemon=True).start()
                        self._json(HTTPStatus.OK, {"ok": True})
                    elif parsed.path == "/test/movement":
                        threading.Thread(target=self._movement_test, daemon=True).start()
                        self._json(HTTPStatus.OK, {"ok": True})
                    elif parsed.path == "/settings":
                        has_mins = "servo_mins" in params
                        has_maxs = "servo_maxs" in params
                        if has_mins or has_maxs:
                            if not has_mins or not has_maxs:
                                raise ValueError("servo_mins and servo_maxs required together")
                            mins = tuple(float(value) for value in params["servo_mins"][0].split(","))
                            maxs = tuple(float(value) for value in params["servo_maxs"][0].split(","))
                            outer.servos.set_calibration_ranges(mins, maxs)
                            if outer.config_path is None:
                                raise OSError("config path is not available")
                            save_servo_ranges(outer.config_path, mins, maxs)
                            outer.animator.set_mode("none")
                        self._json(HTTPStatus.OK, settings_json())
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                except (ValueError, IndexError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                except OSError as exc:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(exc)})

            def _movement_test(self) -> None:
                for value in (0.0, 0.5, -0.5, 0.0):
                    for index in range(5):
                        outer.servos.set_norm(index, value, 25)
                    time.sleep(2)

            def log_message(self, format: str, *args) -> None:
                return

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
