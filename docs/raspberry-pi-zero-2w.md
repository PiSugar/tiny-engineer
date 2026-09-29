# Raspberry Pi Zero 2 W + Whisplay HAT

This port runs Tiny Engineer as a Linux app while leaving the existing ESP32-C3 firmware intact. The Raspberry Pi runtime is under [`raspberry_pi/`](../raspberry_pi/).

## Hardware

| Function | Hardware / interface |
| --- | --- |
| Main controller | Raspberry Pi Zero 2 W |
| Audio input/output | Whisplay HAT through PipeWire/PulseAudio (`pulse`), shared with other apps |
| App LCD, button, RGB LED | Whisplay HAT through `whisplay-daemon` |
| Robot eyes | Original 128×32 SSD1306 OLED, I2C address `0x3c` |
| Five servos | Waveshare Servo Driver HAT / PCA9685, I2C address `0x40`, 50 Hz |

The servo channel order is identical to the original firmware:

| Channel | Joint | Stock safe range |
| ---: | --- | ---: |
| 0 | Head | 60–130° |
| 1 | Neck | 40–130° |
| 2 | Left hand | 45–135° |
| 3 | Right hand | 35–125° |
| 4 | Body | 40–130° |

## Wiring and power

Connect both the PCA9685 and SSD1306 to the Pi I2C bus: SDA on GPIO2 (pin 3), SCL on GPIO3 (pin 5), and logic ground in common. The addresses do not conflict with each other or the Whisplay audio codec.

> [!WARNING]
> Power the servos from a separate regulated 5 V supply rated for their combined stall current. Join its ground to the Pi/HAT ground. Do not power five servos from the Pi 3.3 V rail or the Zero 2 W regulator.

Before attaching horns, verify the channel mapping with one servo at a time. The Waveshare HAT must use address `0x40`; change its address jumpers or `config.json` if another device already claims it.

## Install

Start from a Raspberry Pi OS image that already has the Whisplay driver and daemon installed:

```bash
git clone https://github.com/PiSugar/tiny-engineer.git
cd tiny-engineer
sudo ./raspberry_pi/install.sh
```

The installer enables I2C, creates `raspberry_pi/.venv`, installs the Python dependencies, installs and starts `tiny-engineer.service`, and registers **Tiny Engineer** with `whisplay-daemon`. Reboot after enabling I2C for the first time.

`tiny-engineer.service` is the persistent owner of the PCA9685 servos, original OLED, Whisplay audio, animations, battery monitor, and HTTP server. It starts at boot and restarts after failures. The Whisplay app is only a foreground remote control: it reads `/health`, sends `/anim` requests when the button is clicked, and renders the small action selector. Closing the app does not stop robot motion or the Web UI.

On the daemon home screen, select Tiny Engineer and long-press to open the remote-control app. The Web controller remains available whether or not that app is open.

Edit `raspberry_pi/config.json` to change ALSA device names, I2C addresses, HTTP port, OLED rotation, or calibrated servo limits.

## Control

The Whisplay LCD is intentionally a small action selector: it shows the active animation, the next animation, and live PiSugar battery/charging status. A normal button click advances to and starts the next animation. The daemon's four-click gesture exits to Home.

The browser control panel is loaded directly from the original firmware HTML in `src/http/index_page.cpp`, so its Home, Animations, Tests, Servo, Config, and API views retain the original layout and styling. Open it on port 8080 for the Raspberry Pi runtime.

The Pi web panel also exposes the original **Calibration** flow. It first moves all five shafts slowly to the electrical 90° center for horn installation, then lets you select Head, Neck, Left hand, Right hand, and Body in the stock order. Nudge one joint at a time, mark its safe minimum and maximum, and save. Calibration moves use the original 25°/s speed and intentionally allow the full electrical 0–180° range; saved ranges are persisted to `raspberry_pi/config.json` and immediately clamp normal animations and servo tests.

The port keeps the existing animation names and the primary HTTP shape:

```bash
curl -X POST 'http://PI_ADDRESS:8080/anim?name=typing'
curl -X POST 'http://PI_ADDRESS:8080/anim?name=none'
curl -X POST 'http://PI_ADDRESS:8080/test/servo?index=0&angle=90'
curl -X POST 'http://PI_ADDRESS:8080/test/audio?mode=play'
curl -X POST 'http://PI_ADDRESS:8080/test/audio?mode=record&seconds=3'
curl 'http://PI_ADDRESS:8080/health'
```

Open `http://PI_ADDRESS:8080/` for the browser controller. Microphone tests are saved to `/tmp/tiny-engineer/microphone-test.wav`.

## Troubleshooting

```bash
i2cdetect -y 1             # expect 3c and 40, plus the Whisplay codec
aplay -l
arecord -l
systemctl status whisplay-daemon
tail -f ~/.whisplay-daemon/daemon-app.log
systemctl status tiny-engineer.service
journalctl -u tiny-engineer.service -f
```

If the app opens but servos do not move, check the external 5 V servo rail and common ground before changing software limits. If the OLED is upside-down, set `oled_rotate_180` to `true`.
