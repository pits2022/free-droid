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
# A HC-SR04 "nincs visszhang" jelzése egy ~38 ms-os MAGAS impulzus (datasheet). A régi
# 40 ms-os ablak ezt épphogy elvágta, és a szkript a saját időtúllépését számolta
# távolsággá: "40002 us -> 686.0 cm". 60 ms-mal a 38 ms-os impulzus BEFEJEZETTKÉNT
# látszik, tehát megkülönböztethető a valódi méréstől.
TIMEOUT_S = 0.06
# A szenzor fizikai hatótávja ~4 m. Ami e fölött jönne, az NEM mérés, hanem a "nincs
# visszhang" jelzés félreolvasása — ezért a mérés inkább None-t ad, mint egy hihető,
# de hamis számot.
MAX_HATOTAV_CM = 450.0


def _minta(lgpio, h, pin: int, db: int, koz_s: float) -> list[int]:
    """`db` darab mintavétel a lábról, `koz_s` szünettel — a lista a nyers 0/1 értékek."""
    ki = []
    for _ in range(db):
        time.sleep(koz_s)
        ki.append(lgpio.gpio_read(h, pin))
    return ki


def _trigger(lgpio, h, trig: int) -> None:
    """~12 us-os trigger-impulzus, PONTOSAN időzítve (busy-wait, nem sleep).

    A `time.sleep(1e-5)` Linuxon nem 10 us-ot alszik: a felébresztés szemcsézettsége
    miatt tipikusan 60-100+ us lesz belőle. A datasheet 10 us MINIMUMOT ír, tehát a
    hosszabb impulzus elvben rendben van — de a klónok itt eltérnek, és ez az egyetlen
    változó, amit ingyen ki lehet zárni, mielőtt forrasztásra kerül a sor.
    """
    lgpio.gpio_write(h, trig, 0)
    time.sleep(0.002)
    lgpio.gpio_write(h, trig, 1)
    veg = time.perf_counter() + 12e-6
    while time.perf_counter() < veg:
        pass
    lgpio.gpio_write(h, trig, 0)


def _measure_cm(lgpio, h, trig: int, echo: int) -> float | None:
    _trigger(lgpio, h, trig)

    start = time.perf_counter()
    while lgpio.gpio_read(h, echo) == 0:
        if time.perf_counter() - start > TIMEOUT_S:
            return None
    rise = time.perf_counter()
    while lgpio.gpio_read(h, echo) == 1:
        if time.perf_counter() - rise > TIMEOUT_S:
            return None
    cm = (time.perf_counter() - rise) * SOUND_CM_PER_S / 2.0
    return None if cm > MAX_HATOTAV_CM else cm


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

    # 1. Alapállapot trigger NÉLKÜL.
    minta = _minta(lgpio, h, echo, 200, 0.005)
    magas = sum(minta)
    print(f"trigger nélkül 200 mintából MAGAS: {magas}")
    if magas == len(minta):
        # NEM lépünk ki azonnal: némelyik HC-SR04 klón az Echo-t a KÖVETKEZŐ TRIGGERIG
        # magasan tartja, ha nem jött vissza visszhang (a datasheet 38 ms-ot ír, a klónok
        # gyakran örökké). Egy trigger kioldja a latchet — e nélkül a diagnosztika egy
        # ÖNMAGA OKOZTA állapotra mondaná, hogy "az Echo a VCC-re van kötve".
        print("  -> az Echo magas; egy triggerrel próbálom kioldani (latch?)")
        lgpio.gpio_write(h, trig, 1)
        time.sleep(1e-5)
        lgpio.gpio_write(h, trig, 0)
        time.sleep(0.1)
        ujra = sum(_minta(lgpio, h, echo, 20, 0.005))
        if ujra == 20:
            print("     -> továbbra is magas: az Echo tényleg a VCC-n van, vagy Trig/Echo cserélve")
            return
        print("     -> kioldódott: LATCH volt, nem bekötési hiba")
    if 0 < magas < len(minta):
        print("  -> az Echo BILLEG trigger nélkül: zajos vagy rosszul érintkező vezeték")
        return

    # 1b. PULL-UP PRÓBA — ez dönti el, hogy a láb HOZZÁ VAN-E KÖTVE bármihez.
    #
    # A fenti "stabil alacsony" ÖNMAGÁBAN SEMMIT NEM BIZONYÍT, és ezen 2026-08-14-én
    # elcsúsztunk: a Pi-n a GPIO 9-27 lábakon ALAPBÓL BELSŐ PULL-DOWN van, tehát egy
    # BE NEM KÖTÖTT láb is stabil 0-t ad. A GPIO22 és GPIO23 is ide esik.
    #
    # Belső FELHÚZÁSSAL viszont szétválik a két eset:
    #   felhúzva MAGAS  -> a lábon nincs semmi: LEBEG (nincs vezeték, vagy a szenzor
    #                      nem kap tápot, tehát a kimenete nagy impedanciás)
    #   felhúzva ALACSONY -> valami AKTÍVAN alacsonyan tartja: a szenzor be van kötve
    #                      ÉS kap tápot (nyugalmi Echo = 0)
    lgpio.gpio_free(h, echo)
    lgpio.gpio_claim_input(h, echo, lgpio.SET_PULL_UP)
    time.sleep(0.01)
    felhuzva = _minta(lgpio, h, echo, 50, 0.002)
    lgpio.gpio_free(h, echo)
    # A Pi pull-beállítása HARDVERES és TÚLÉLI a folyamatot — ha felhúzva hagynánk, a
    # KÖVETKEZŐ futás alapállapot-mérése hamis képet adna. Explicit visszaállítás.
    lgpio.gpio_claim_input(h, echo, lgpio.SET_PULL_DOWN)
    print(f"belső FELHÚZÁSSAL 50 mintából magas: {sum(felhuzva)}")
    if sum(felhuzva) > len(felhuzva) // 2:
        print("  -> a láb LEBEG: semmi nem húzza a belső felhúzás ellenében.")
        print("     OSZTÓ NÉLKÜL ez kétféle lehet: nincs ott a vezeték, VAGY a szenzor")
        print("     nem kap tápot (a kimenete táp nélkül nagy impedanciás — ugyanígy néz ki).")
        print("     OSZTÓVAL viszont EGYÉRTELMŰ, és a FÖLD felé mutat:")
        print("       a 20k a földre AKKOR IS lehúzná ezt a lábat, ha a szenzornak nincs")
        print("       tápja — tehát a táphiány mint egyedüli ok KIZÁRVA. Ami marad: a")
        print(f"       GPIO{echo} -> 20k -> GND út valahol SZAKADT.")
        print("     MÉRD EBBEN A SORRENDBEN: 1. szenzor GND <-> Pi GND folytonosság")
        print("     (fő gyanúsított), 2. VCC <-> GND ~5 V, 3. osztó közepe <-> a GPIO-láb.")
        return
    # ⚠️ EZ A KÖVETKEZTETÉS CSAK OSZTÓ NÉLKÜL ÉRVÉNYES, és 2026-08-14-én emiatt tévedtem.
    # Az 5 V-os bekötéshez feszültségosztó kell (10k az Echo felől, 20k a földre). A 20k a
    # Pi belső felhúzása ELLEN dolgozik: 3,3 V * 20/(50+20) ~ 0,94 V, ami a logikai küszöb
    # ALATT van — tehát a láb AKKOR IS alacsonyat ad, ha a szenzor TÁP NÉLKÜL van és a
    # kimenete nagy impedanciás. A próba osztóval NEM tudja megkülönböztetni a "bekötve és
    # táp alatt" esetet a "nincs tápja" esettől.
    #
    # A FORDÍTOTT IRÁNY VISZONT OSZTÓVAL IS ÉRVÉNYES, és ezt 2026-08-15-én mértük ki: ha a
    # láb felhúzva MAGAS marad, az osztó jelenlétében BIZONYÍTÉK, hogy a 20k nem éri el a
    # földet (különben 0,94 V-ot, azaz alacsonyat adna). A "lebeg" ág üzenete ezért osztó
    # mellett a FÖLDRE mutat, nem a tápra — lásd fent.
    print("  -> a láb alacsonyan van a felhúzás ellenében.")
    print("     OSZTÓ NÉLKÜL ez azt jelenti: a szenzor bekötve ÉS táp alatt.")
    print("     OSZTÓVAL viszont SEMMIT NEM JELENT — a földre menő ellenállás magától is")
    print("     leviszi a lábat. Ilyenkor a szenzor tápját KÜLÖN kell ellenőrizni.")

    # 2. Trigger után: felfut-e egyáltalán? Öt próba, mert a 3,3 V-on marginálisan
    # működő szenzor SZAKASZOSAN válaszol — három próba még mutathat véletlen nullát.
    for i in range(5):
        _trigger(lgpio, h, trig)

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
        cm = szeles_us * SOUND_CM_PER_S * 1e-6 / 2
        if szeles_us > TIMEOUT_S * 1e6 * 0.98:
            # Az impulzus a saját ablakunkig tartott: NEM mérés, hanem elakadás.
            print(f"  {i+1}. trigger: az Echo {szeles_us:.0f} us után SEM futott le "
                  f"(a mérőablak vége) -> beragadt magasan")
        elif 30000 < szeles_us < 45000:
            print(f"  {i+1}. trigger: {szeles_us:8.0f} us = a datasheet ~38 ms-os "
                  f"NINCS-VISSZHANG jelzése (a szenzor VÁLASZOL, de nem kap vissza jelet)")
        elif cm > MAX_HATOTAV_CM:
            print(f"  {i+1}. trigger: {szeles_us:8.0f} us -> {cm:.0f} cm, ami a ~4 m-es "
                  f"hatótáv FÖLÖTT van: nem valódi mérés")
        else:
            print(f"  {i+1}. trigger: Echo impulzus {szeles_us:8.0f} us -> {cm:5.1f} cm")
        time.sleep(0.07)   # a datasheet 60 ms-ot kér két mérés közé

    print("\nOLVASAT:")
    print("  Ha ~38 ms-os NINCS-VISSZHANG jelzés jött: a szenzor LOGIKÁJA MŰKÖDIK (a")
    print("  triggerre válaszol), csak nem kap vissza jelet. Ha van tárgy 4 m-en belül,")
    print("  akkor az ADÓ gyenge — tipikusan 5 V-only panel 3,3 V-on. Ez a spec döntési")
    print("  eljárásának 3. lépése: VCC -> 5 V, ÉS FESZÜLTSÉGOSZTÓ AZ ECHO-RA (1k + 2k).")
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
            # EXPLICIT PULL-DOWN a foglalásnál, nem az alapértelmezésre hagyva.
            #
            # MÉRT ok (2026-08-14): a Pi pull-beállítása HARDVERES és TÚLÉLI a folyamatot.
            # Egy korábbi futás felhúzás-próbája bekapcsolva hagyta a pull-upot, és
            # onnantól MINDEN futás "az Echo VÉGIG magas" alapállapotot mért — a szkript
            # pedig bekötési hibát jelzett (`az Echo a VCC-n van`) egy ÖNMAGA hagyta
            # állapotra. Egy órányi hibakeresést vitt el.
            #
            # A tanulság általános: ha egy műszer állítja a hardver állapotát, akkor
            # ISMERT ÁLLAPOTBÓL kell indulnia, nem az előző futáséból.
            lgpio.gpio_claim_input(h, sensor["echo"], lgpio.SET_PULL_DOWN)

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
                    # Ismert állapotból: a pull HARDVERES és túléli a folyamatot (lásd fent).
                    lgpio.gpio_claim_input(h, echo, lgpio.SET_PULL_DOWN)
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
