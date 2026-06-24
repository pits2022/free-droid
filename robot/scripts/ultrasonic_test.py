#!/usr/bin/env python3
"""Phase 1.5 smoke test — print live distances from the 3 HC-SR04P sensors.

front / front_left / front_right, pins from freedroid.config.gpio. HC-SR04P is
3.3 V-tolerant so Echo wires straight to the GPIO (no divider).
Run on the Pi:  uv run python scripts/ultrasonic_test.py   (Ctrl-C to stop)
"""

from __future__ import annotations

import time

import _hw

from freedroid.config import gpio as G

SOUND_CM_PER_S = 34300.0
TIMEOUT_S = 0.04  # ~6.8 m ceiling


def _measure_cm(lgpio, h, trig: int, echo: int) -> float | None:
    lgpio.gpio_write(h, trig, 0)
    time.sleep(0.002)
    lgpio.gpio_write(h, trig, 1)
    time.sleep(1e-5)  # 10 µs trigger
    lgpio.gpio_write(h, trig, 0)

    start = time.perf_counter()
    while lgpio.gpio_read(h, echo) == 0:
        if time.perf_counter() - start > TIMEOUT_S:
            return None
    rise = time.perf_counter()
    while lgpio.gpio_read(h, echo) == 1:
        if time.perf_counter() - rise > TIMEOUT_S:
            return None
    return (time.perf_counter() - rise) * SOUND_CM_PER_S / 2.0


def main() -> int:
    import lgpio

    h = _hw.open_gpiochip()

    try:
        for sensor in G.ULTRASONIC.values():
            lgpio.gpio_claim_output(h, sensor["trig"], 0)
            lgpio.gpio_claim_input(h, sensor["echo"])

        while True:
            readings = []
            for name, sensor in G.ULTRASONIC.items():
                cm = _measure_cm(lgpio, h, sensor["trig"], sensor["echo"])
                readings.append(f"{name}={'--' if cm is None else f'{cm:5.1f}cm'}")
                time.sleep(0.03)  # avoid cross-echo between sensors
            print("  ".join(readings))
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    raise SystemExit(main())
