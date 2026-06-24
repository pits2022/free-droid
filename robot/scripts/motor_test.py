#!/usr/bin/env python3
"""Phase 1.5 smoke test — drive both tracks forward then backward.

Cytron HAT-MDD10 via lgpio. Pins come from freedroid.config.gpio (single source).
Run on the Pi:  uv run python scripts/motor_test.py [--duty 40] [--seconds 1.5]
Low duty by default; keep the robot propped up / wheels free on first run.
"""

from __future__ import annotations

import argparse
import time

import _hw

from freedroid.config import gpio as G

PWM_FREQ = 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duty", type=float, default=40.0, help="PWM duty %% (0-100)")
    ap.add_argument("--seconds", type=float, default=1.5, help="run time per direction")
    args = ap.parse_args()

    import lgpio

    h = _hw.open_gpiochip()
    for pin in (G.LEFT_MOTOR_PWM, G.LEFT_MOTOR_DIR, G.RIGHT_MOTOR_PWM, G.RIGHT_MOTOR_DIR):
        lgpio.gpio_claim_output(h, pin, 0)

    def drive(duty: float) -> None:
        lgpio.tx_pwm(h, G.LEFT_MOTOR_PWM, PWM_FREQ, duty)
        lgpio.tx_pwm(h, G.RIGHT_MOTOR_PWM, PWM_FREQ, duty)

    try:
        for label, direction in (("FORWARD", 0), ("BACKWARD", 1)):
            print(f"{label} @ {args.duty:.0f}% for {args.seconds}s")
            lgpio.gpio_write(h, G.LEFT_MOTOR_DIR, direction)
            lgpio.gpio_write(h, G.RIGHT_MOTOR_DIR, direction)
            drive(args.duty)
            time.sleep(args.seconds)
            drive(0)
            time.sleep(0.5)
        print("OK — both motors moved forward and backward")
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        drive(0)
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    raise SystemExit(main())
