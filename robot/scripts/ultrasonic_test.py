#!/usr/bin/env python3
"""Phase 1.5 smoke test — élő távolság a HC-SR04(P) szenzorokról.

Lábak a freedroid.config.gpio-ból (egyetlen forrás). A "P" változat 3,3 V-tűrő, tehát
az Echo közvetlenül a GPIO-ra megy; sima 5 V-os panelnél 3,3 V-os TÁP mellett szintén
biztonságos, mert a kimenet szintjét a táp határolja (lásd a spec döntési eljárását).

    uv run python scripts/ultrasonic_test.py                  # mind a három
    uv run python scripts/ultrasonic_test.py --sensor front   # csak az elülső
"""

from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Bekötésnél EGY szenzort mérj. A BE NEM KÖTÖTT lábak lebegnek, és a lebegő Echo
    # néha ad egy random impulzust — a kimenetben az megkülönböztethetetlen egy valódi
    # méréstől. Egy szenzorra szűkítve a "--" egyértelműen azt jelenti: nincs visszhang.
    ap.add_argument("--sensor", choices=(*G.ULTRASONIC, "all"), default="all",
                    help="melyik szenzort mérjük (bekötésnél egyet: --sensor front)")
    args = ap.parse_args()
    valasztott = (dict(G.ULTRASONIC) if args.sensor == "all"
                  else {args.sensor: G.ULTRASONIC[args.sensor]})

    import lgpio

    h = _hw.open_gpiochip()

    try:
        for nev, sensor in valasztott.items():
            print(f"  {nev}: trig=GPIO{sensor['trig']}  echo=GPIO{sensor['echo']}")
            lgpio.gpio_claim_output(h, sensor["trig"], 0)
            lgpio.gpio_claim_input(h, sensor["echo"])

        while True:
            readings = []
            for name, sensor in valasztott.items():
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
