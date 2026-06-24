#!/usr/bin/env python3
"""Phase 1.5 smoke test — sweep the pan/tilt servos on the PCA9685.

CH0 = pan, CH1 = tilt (from freedroid.config.gpio). 50 Hz, 1.0–2.0 ms pulses,
returning to centre. Run on the Pi:  uv run python scripts/servo_test.py
"""

from __future__ import annotations

import time

from freedroid.config import gpio as G

PERIOD_MS = 20.0  # 50 Hz
CENTRE_MS = 1.5
SWEEP_MS = (1.0, 1.5, 2.0, 1.5, 1.0)


def main() -> int:
    import board
    import busio
    from adafruit_pca9685 import PCA9685

    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c, address=G.PCA9685_ADDR)
    pca.frequency = 50

    def set_pulse(channel: int, ms: float) -> None:
        pca.channels[channel].duty_cycle = int(ms / PERIOD_MS * 0xFFFF)

    try:
        for channel, label in ((G.PAN_CHANNEL, "pan"), (G.TILT_CHANNEL, "tilt")):
            print(f"sweeping {label} (CH{channel})")
            for ms in SWEEP_MS:
                set_pulse(channel, ms)
                time.sleep(0.4)
            set_pulse(channel, CENTRE_MS)
            time.sleep(0.4)
        print("OK — pan and tilt swept and centred")
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        pca.deinit()


if __name__ == "__main__":
    raise SystemExit(main())
