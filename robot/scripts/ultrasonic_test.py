#!/usr/bin/env python3
"""Phase 1.5 smoke test — élő távolság a HC-SR04(P) szenzorokról.

Lábak a freedroid.config.gpio-ból (egyetlen forrás). A "P" változat 3,3 V-tűrő, tehát
az Echo közvetlenül a GPIO-ra megy; sima 5 V-os panelnél 3,3 V-os TÁP mellett szintén
biztonságos, mert a kimenet szintjét a táp határolja (lásd a spec döntési eljárását).

    uv run python scripts/ultrasonic_test.py                  # mind a három
    uv run python scripts/ultrasonic_test.py --sensor front   # csak az elülső
    uv run python scripts/ultrasonic_test.py --sensor front --diag   # hibakeresés
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


def _diagnosztika(lgpio, h, nev: str, trig: int, echo: int) -> None:
    """Miért nincs visszhang — a NÉGY ok szétválasztása.

    A "nézd át a bekötést" négy külön hibát takar, és mind másképp néz ki az Echo lábon:

      1. Az Echo VÉGIG alacsony, trigger után sem mozdul
         -> a szenzor nem válaszol: nincs táp, rossz GPIO, vagy 5 V-only panel 3,3 V-on
      2. Az Echo VÉGIG magas, trigger nélkül is
         -> az Echo a VCC-re van kötve, vagy a Trig/Echo fel van cserélve
      3. Az Echo trigger NÉLKÜL is billeg
         -> a láb LEBEG (nincs bekötve), a szám random lenne
      4. Az Echo szépen felfut és lefut, csak a mérés hosszú
         -> a bekötés JÓ, a tárgy van túl messze (a `--` ilyenkor helyes válasz)
    """
    print(f"\n=== diagnosztika: {nev} (trig=GPIO{trig}, echo=GPIO{echo}) ===")

    # 1. Alapállapot trigger NÉLKÜL: egy nyugvó HC-SR04 Echo lába stabil ALACSONY.
    minta = [lgpio.gpio_read(h, echo) for _ in range(200) if not time.sleep(0.005)]
    magas = sum(minta)
    print(f"trigger nélkül 200 mintából MAGAS: {magas}")
    if magas == len(minta):
        print("  -> az Echo VÉGIG magas: valószínűleg a VCC-re van kötve, vagy Trig/Echo cserélve")
        return
    if 0 < magas < len(minta):
        print("  -> az Echo BILLEG trigger nélkül: a láb valószínűleg LEBEG (nincs bekötve)")
        return
    print("  -> alapállapot rendben (stabil alacsony)")

    # 2. Trigger után: felfut-e egyáltalán?
    for i in range(3):
        lgpio.gpio_write(h, trig, 0)
        time.sleep(0.002)
        lgpio.gpio_write(h, trig, 1)
        time.sleep(1e-5)
        lgpio.gpio_write(h, trig, 0)

        t0 = time.perf_counter()
        felfutott = False
        while time.perf_counter() - t0 < TIMEOUT_S:
            if lgpio.gpio_read(h, echo) == 1:
                felfutott = True
                break
        if not felfutott:
            print(f"  {i+1}. trigger: az Echo NEM futott fel {TIMEOUT_S*1000:.0f} ms alatt")
            continue
        rise = time.perf_counter()
        while lgpio.gpio_read(h, echo) == 1 and time.perf_counter() - rise < TIMEOUT_S:
            pass
        szeles_us = (time.perf_counter() - rise) * 1e6
        print(f"  {i+1}. trigger: Echo impulzus {szeles_us:8.0f} us "
              f"-> {szeles_us * 34300e-6 / 2:.1f} cm")
        time.sleep(0.07)   # a datasheet 60 ms-ot kér két mérés közé
    else:
        return

    print("\nHA EGYIK TRIGGERRE SEM FUTOTT FEL az Echo, a sorrend:")
    print("  a) VCC és GND tényleg be van kötve? (közös föld a Pi-vel!)")
    print("  b) Trig/Echo nincs felcserélve? (a szkript fent kiírja, melyik láb melyik)")
    print("  c) 3,3 V-ról megy a szenzor? Ha a panel 5 V-only HC-SR04, ezen a ponton")
    print("     kell 5 V-ra váltani — ÉS AKKOR AZ ECHO-RA FESZÜLTSÉGOSZTÓ KELL (1k + 2k),")
    print("     különben az 5 V-os Echo tönkreteheti a Pi 3,3 V-os GPIO-ját.")
    print("     (Ez a spec döntési eljárásának 3. lépése — pont ez az ág.)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Bekötésnél EGY szenzort mérj. A BE NEM KÖTÖTT lábak lebegnek, és a lebegő Echo
    # néha ad egy random impulzust — a kimenetben az megkülönböztethetetlen egy valódi
    # méréstől. Egy szenzorra szűkítve a "--" egyértelműen azt jelenti: nincs visszhang.
    ap.add_argument("--sensor", choices=(*G.ULTRASONIC, "all"), default="all",
                    help="melyik szenzort mérjük (bekötésnél egyet: --sensor front)")
    ap.add_argument("--diag", action="store_true",
                    help="ha csak `--` jön: megkülönbözteti a lehetséges okokat")
    ap.add_argument("--swap", action="store_true",
                    help="a Trig és Echo szerepét MEGCSERÉLI (csak --diag mellett): "
                         "ha így megszólal, a két vezeték fel van cserélve")
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

        if args.diag:
            for nev, sensor in valasztott.items():
                trig, echo = sensor["trig"], sensor["echo"]
                if args.swap:
                    # A SZEREPEK cseréje szoftverből: ha a két VEZETÉK van felcserélve,
                    # így megszólal a szenzor — hardverhez nyúlni sem kell hozzá.
                    #
                    # ⚠️ RÖVID ÜTKÖZÉS: ha a bekötés MÉGIS helyes, akkor most a szenzor
                    # Echo-KIMENETÉRE hajtunk 10 us-ig. Mindkét oldal áramkorlátos, és
                    # a jelen mért állapotban az Echo VÉGIG ALACSONY (3/3 trigger), tehát
                    # a magas impulzusunk alatt sincs mit ellene hajtania — ezért
                    # vállalható. Tartós hajtásra NE használd.
                    trig, echo = echo, trig
                    lgpio.gpio_free(h, sensor["trig"])
                    lgpio.gpio_free(h, sensor["echo"])
                    lgpio.gpio_claim_output(h, trig, 0)
                    lgpio.gpio_claim_input(h, echo)
                    print(f"\n[SWAP] most trig=GPIO{trig}, echo=GPIO{echo}")
                _diagnosztika(lgpio, h, nev, trig, echo)
            return 0

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
