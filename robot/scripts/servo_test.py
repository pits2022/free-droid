#!/usr/bin/env python3
"""Phase 1.5 smoke test — pan/tilt szervók a PCA9685-ön.

CH0 = pan, CH1 = tilt (a freedroid.config.gpio-ból), 50 Hz.

ELSŐ bekapcsolásnál KIS kitéréssel indíts, egy csatornán:

    uv run python scripts/servo_test.py --channel pan --range 0.15
    uv run python scripts/servo_test.py --centre-only     # csak középre áll

MIÉRT: a teljes 1,0-2,0 ms kitérés a szervó VÉGÁLLÁSA. Ha a kamera-tartó mechanikusan
szűkebb, a szervó nekifeszül az ütközőnek és MEGRÁNTOTT áramot vesz fel (MG996R:
~2,5 A/db), miközben a szervó-sín az LM2596-ról jön, ami 2 A-es. Két szervó egyszerre
végállásban tehát a TÁPOT viszi el — és a Pi vele mehet. Kis kitéréssel előbb kiderül,
merre van hely.
"""

from __future__ import annotations

import argparse
import time

from freedroid.config import gpio as G

PERIOD_MS = 20.0  # 50 Hz
CENTRE_MS = 1.5
TELJES_KITERES_MS = 0.5   # a szervó végállása a középtől: 1,0 ms ... 2,0 ms


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", choices=("pan", "tilt", "both"), default="both",
                    help="melyik szervót mozgassuk (elsőre egyet)")
    ap.add_argument("--range", type=float, default=TELJES_KITERES_MS, metavar="MS",
                    help=f"kitérés a középtől ms-ban (alap: {TELJES_KITERES_MS} = végállás; "
                         f"első bekapcsolásnál 0.15 ajánlott)")
    ap.add_argument("--centre-only", action="store_true",
                    help="csak középre áll és ott marad (a mechanika ellenőrzésére)")
    args = ap.parse_args()
    if not 0 < args.range <= TELJES_KITERES_MS:
        ap.error(f"--range 0 és {TELJES_KITERES_MS} között legyen (ms a középtől)")

    import board
    import busio
    from adafruit_pca9685 import PCA9685

    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c, address=G.PCA9685_ADDR)
    pca.frequency = 50

    def set_pulse(channel: int, ms: float) -> None:
        pca.channels[channel].duty_cycle = int(ms / PERIOD_MS * 0xFFFF)

    csatornak = {"pan": [(G.PAN_CHANNEL, "pan")], "tilt": [(G.TILT_CHANNEL, "tilt")],
                 "both": [(G.PAN_CHANNEL, "pan"), (G.TILT_CHANNEL, "tilt")]}[args.channel]

    try:
        for channel, label in csatornak:
            print(f"{label} (CH{channel}) -> KÖZÉP ({CENTRE_MS} ms)")
            set_pulse(channel, CENTRE_MS)
            time.sleep(0.6)
            if args.centre_only:
                continue
            # Középről indul és oda is tér vissza: az ütközőnek feszülés esélye így a
            # legkisebb, és minden lépés után van egy ismert, biztonságos állapot.
            for ms in (CENTRE_MS - args.range, CENTRE_MS,
                       CENTRE_MS + args.range, CENTRE_MS):
                print(f"  {ms:.2f} ms")
                set_pulse(channel, ms)
                time.sleep(0.5)
        print(f"OK — {args.channel} kész (kitérés ±{args.range} ms). Amit fel kell írni: "
              f"MOZDULT-e, MERRE, és nem feszül-e neki valaminek a végén.")
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        pca.deinit()


if __name__ == "__main__":
    raise SystemExit(main())
