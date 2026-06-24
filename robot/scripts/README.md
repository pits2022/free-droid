# Hardware smoke-test scripts (Phase 1.5)

Standalone **bring-up** scripts that exercise the hardware directly — *before* the
control software exists — to confirm wiring. They are **Pi-only** (need `lgpio` /
`adafruit-circuitpython-pca9685`, installed by `uv sync`) and read their pin/channel
map from `freedroid.config.gpio`, so there's a single source of truth.

Run each from the `robot/` directory on the Pi:

```bash
uv run python scripts/<name>.py
```

| Checklist item (docs/free-droid.md, Fázis 1.5) | Script |
| :--- | :--- |
| Motor teszt: mindkét motor előre/hátra | `motor_test.py` |
| Szervó teszt: PCA9685 sweep CH0/CH1 | `servo_test.py` |
| HC-SR04P teszt: távolságmérés kiírása | `ultrasonic_test.py` |
| USB eszközök: `lsusb`, `arecord -l`, `aplay -l` | `usb_devices.py` |
| USB LTE modem: HiLink felmegy-e, van-e net | `lte_modem_test.py` |
| Mikrofon-választás: webcam vs. omni + ALSA | `mic_select.py` |

> ⚠️ **Safety:** `motor_test.py` and `servo_test.py` move the robot. Prop the chassis
> up so the tracks spin free, and keep the pan/tilt arc clear, on the first run.
> Both default to low effort and recentre/stop in a `finally` block (also on Ctrl-C).

These are intentionally *not* part of the installed `freedroid` package — they are
operator tools. The repeatable, automated checks live in `freedroid.health`
(`freedroid-health`) and the pytest suite.
