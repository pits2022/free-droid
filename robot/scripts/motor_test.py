#!/usr/bin/env python3
"""Phase 1.5 smoke test — drive both tracks forward then backward.

Cytron HAT-MDD10 via lgpio. Pins come from freedroid.config.gpio (single source).
Run on the Pi:  uv run python scripts/motor_test.py [--duty 40] [--seconds 1.5]
Low duty by default; keep the robot propped up / wheels free on first run.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

import _hw

from freedroid.config import gpio as G

# A frekvencia és az "előre" logikai szint a configból jön, nem innen: azok
# KALIBRÁCIÓS értékek (a motor bekötésén múlnak), és egy helyen kell élniük.
PWM_FREQ = G.PWM_FREQ_HZ


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duty", type=float, default=40.0, help="PWM duty %% (0-100)")
    ap.add_argument("--seconds", type=float, default=1.5, help="run time per direction")
    # ELSŐ bekötésnél EGY motort hajts. Két motor egyszerre nem mondja meg, melyik a
    # bal és melyik a jobb, sem azt, hogy az "előre" tényleg előre visz — és pont ez a
    # két dolog az, amit a lábkiosztás NEM dönt el (lásd config/gpio.py kalibrációs
    # jegyzetét). A `both` a regresszió-próba, ha már tudjuk, mi micsoda.
    ap.add_argument("--motor", choices=("left", "right", "both"), default="both",
                    help="melyik motort hajtsuk (első bekötésnél EGYET: --motor left)")
    args = ap.parse_args()

    # Az "előre" szint OLDALANKÉNT más (a motorok tükörképben vannak beépítve) — a
    # próbának ugyanazt a configot kell használnia, amit az éles vezérlés, különben a
    # teszt zöld lesz és a robot mégis helyben pörög.
    BAL = ("BAL", G.LEFT_MOTOR_PWM, G.LEFT_MOTOR_DIR, G.LEFT_FORWARD_LEVEL)
    JOBB = ("JOBB", G.RIGHT_MOTOR_PWM, G.RIGHT_MOTOR_DIR, G.RIGHT_FORWARD_LEVEL)
    valasztott = {"left": [BAL], "right": [JOBB], "both": [BAL, JOBB]}[args.motor]

    import lgpio

    # Translate SIGTERM (e.g. `kill`, systemd stop) into a clean exit so the
    # finally block still cuts the motors instead of leaving a track spinning.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    h = _hw.open_gpiochip()

    def stop_all() -> None:
        # Each motor stopped independently — a failure on one must not skip the other.
        for pwm in (G.LEFT_MOTOR_PWM, G.RIGHT_MOTOR_PWM):
            try:
                lgpio.tx_pwm(h, pwm, PWM_FREQ, 0)
            except Exception as e:  # noqa: BLE001 - best-effort stop
                print(f"motor_test: WARNING failed to stop PWM {pwm}: {e}", file=sys.stderr)

    try:
        for pin in (G.LEFT_MOTOR_PWM, G.LEFT_MOTOR_DIR, G.RIGHT_MOTOR_PWM, G.RIGHT_MOTOR_DIR):
            lgpio.gpio_claim_output(h, pin, 0)

        for nev, pwm_pin, dir_pin, elore in valasztott:
            for label, szint in (("ELŐRE", elore), ("HÁTRA", elore ^ 1)):
                print(f"{nev} / {label} @ {args.duty:.0f}% — {args.seconds}s "
                      f"(PWM={pwm_pin}, DIR={dir_pin}={szint})")
                # SORREND: előbb az irány, aztán a PWM. Fordítva egy pillanatra a
                # KORÁBBI irányba indulna a motor, ami első bekötésnél épp azt a
                # kérdést zavarja össze, amit mérni akarunk.
                lgpio.gpio_write(h, dir_pin, szint)
                lgpio.tx_pwm(h, pwm_pin, PWM_FREQ, args.duty)
                time.sleep(args.seconds)
                stop_all()
                time.sleep(0.5)
        print(f"OK — lefutott ({args.motor}). Amit most fel kell írni: melyik LÁNCTALP "
              f"mozgott, és az 'ELŐRE' tényleg előre vitt-e. Ha a rossz lánctalp mozgott, "
              f"a config/gpio.py-ban a két PWM/DIR PÁRT cseréld; ha az irány fordított, "
              f"a {'LEFT' if args.motor == 'left' else 'RIGHT'}_FORWARD_LEVEL-t.")
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        stop_all()
        try:
            lgpio.gpiochip_close(h)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


if __name__ == "__main__":
    raise SystemExit(main())
