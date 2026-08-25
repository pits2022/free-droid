#!/usr/bin/env python3
"""A kamera-szervók bemérése — `ms_per_deg`, a biztonságos pulzus-sáv, és a holtjáték.

HÁROM SZÁM tengelyenként. Mindhárom MÉRVE van (2026-08-25, ezzel a scripttel) — ez a
futtatás az ÚJRAMÉRÉS eszköze: szervócsere, áthelyezett horn vagy új tartó után.

  1. `ms_per_deg` — hány ms a szervón egy fok. A `camera pan left 45` enélkül nem 45
     fok, csak "arra". MÉRVE: pan 0,0133, tilt 0,0112 — a kettő 19%-kal eltér, tehát
     tengelyenként kell. (Két korábbi SZEMMÉRTÉKES becslés, 0,010 és 0,020, is tévedett.)
  2. `min_ms` / `max_ms` — a biztonsági sáv. MÉRVE: 0,60-2,40 ms, ami ±68 (pan) / ±80
     (tilt) fok. A korábbi 1,0-2,0-es TIPP csak ±25 fokot engedett, amiben egy
     "fordulj balra 45 fokot" mindig vágásba futott.
  3. A HOLTJÁTÉK (a fogaskerekek hézaga). MÉRVE: pan 10, tilt 5 fok. Ez magyarázza, hogy
     a gesztusok után a kamera nem pontosan oda állt vissza, ahonnan indult — a szoftver
     végig a HELYES pulzust adta ki, tehát a hiba a mechanikában volt, nem a számításban.
     A vezérlő ezt most a záró mozdulat egyirányú közelítésével egyenlíti ki.

A MÉRÉS ELVE, és ezért olcsóbb, mint hinnéd: nem egy MOZDULAT nagyságát saccoljuk meg
(azt rosszul csinálja az ember), hanem KÉT ÁLLÓ HELYZETET hasonlítunk össze. A szervó
odaáll, ott marad, és van időd szögmérőt tenni mellé.

    cd /opt/free-droid/robot
    uv run python scripts/calibrate_camera.py --channel pan
    uv run python scripts/calibrate_camera.py --channel tilt --explore

⚠️ `--explore` a biztonsági sávon KÍVÜLRE is enged. A szervó ott nekifeszülhet a
mechanikai ütközőnek, és az MG996R olyankor ~2,5 A-t vesz fel a 2 A-es LM2596-sínről —
két szervó együtt a TÁPOT viszi, a Pi-vel együtt. A script ezért egyesével lépked és
minden lépés után MEGKÉRDEZ. Ha zúg, remeg vagy melegszik: nemet mondj.
"""

from __future__ import annotations

import argparse
import time

from freedroid.camera import tengelyek
from freedroid.config import gpio as G
from freedroid.config.settings import load_settings

PERIOD_MS = 20.0            # 50 Hz
KUTATO_SAV = (0.6, 2.4)     # --explore mellett; a hobbiszervók szokásos abszolút határa
LEPES_MS = 0.05             # ekkorákat lépünk kifelé a végállás keresésekor


def _szam(kerdes: str) -> float | None:
    """Számot kér. Üres/érvénytelen/EOF -> None (kihagyás)."""
    try:
        valasz = input(kerdes).strip().replace(",", ".")
    except EOFError:
        return None
    if not valasz:
        return None
    try:
        return float(valasz)
    except ValueError:
        print("   nem szám, kihagyom")
        return None


def _igen(kerdes: str) -> bool:
    """Megerősítés. EOF -> NEM: TTY nélkül nincs, aki azt mondja, hogy biztonságos."""
    try:
        return input(kerdes).strip().lower() in ("i", "igen", "y", "yes")
    except EOFError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", choices=("pan", "tilt"), required=True)
    ap.add_argument("--explore", action="store_true",
                    help="a biztonsági sávon KÍVÜL is keressük a végállást (lásd a fejlécet)")
    ap.add_argument("--seconds", type=float, default=8.0,
                    help="meddig tartsa az egyes állásokat, hogy le tudd mérni")
    args = ap.parse_args()

    cfg = load_settings().camera
    pan_t, tilt_t = tengelyek(cfg)
    t = pan_t if args.channel == "pan" else tilt_t
    csatorna = t.csatorna

    import board
    import busio
    from adafruit_pca9685 import PCA9685

    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c, address=G.PCA9685_ADDR)
    pca.frequency = cfg.pwm_frequency_hz

    def allit(ms: float) -> None:
        pca.channels[csatorna].duty_cycle = int(ms / PERIOD_MS * 0xFFFF)

    def tarts(ms: float, uzenet: str) -> None:
        print(f"\n>>> {ms:.2f} ms — {uzenet}")
        allit(ms)
        time.sleep(args.seconds)

    try:
        also, felso = t.min_ms, t.max_ms

        # ── 1. a sáv végállásai (opcionálisan tágítva) ───────────────────────────
        if args.explore:
            print("\n=== VÉGÁLLÁS-KERESÉS ===")
            print("Minden lépés után kérdezek. Ha a szervó zúg, remeg, melegszik, vagy a")
            print("tartó nekifeszül valaminek: NEM. Az UTOLSÓ jó érték lesz a határ.")
            for nev, irany, korlat in (("min_ms", -1, KUTATO_SAV[0]),
                                       ("max_ms", +1, KUTATO_SAV[1])):
                hatar = also if irany < 0 else felso
                while True:
                    kovetkezo = round(hatar + irany * LEPES_MS, 3)
                    if (irany < 0 and kovetkezo < korlat) or (irany > 0 and kovetkezo > korlat):
                        print(f"   elértük a kutató-sáv szélét ({korlat} ms), megállok")
                        break
                    tarts(kovetkezo, f"{nev} tágítása — FIGYELD ÉS HALLGASD")
                    if not _igen("   Rendben volt? (i/n) "):
                        print(f"   -> {nev} marad {hatar:.2f} ms")
                        break
                    hatar = kovetkezo
                if irany < 0:
                    also = hatar
                else:
                    felso = hatar

        # ── 2. a skála: két álló helyzet közti TELJES kitérés ────────────────────
        print("\n=== SKÁLA ===")
        tarts(also, "ez az EGYIK végállás — jelöld meg (papír, szögmérő, fotó)")
        tarts(felso, "ez a MÁSIK végállás — mérd meg a KETTŐ KÖZTI szöget")
        teljes = _szam(f"   Hány FOK a két állás között? (a sáv {also:.2f}-{felso:.2f} ms) ")

        ms_per_deg = None
        if teljes and teljes > 0:
            ms_per_deg = (felso - also) / teljes
            print(f"   -> ms_per_deg = ({felso:.2f} - {also:.2f}) / {teljes} = {ms_per_deg:.4f}")
        else:
            print("   kihagyva — a skála marad a jelenlegi")
            ms_per_deg = t.ms_per_deg

        # ── 3. holtjáték: ugyanaz a pulzus, két IRÁNYBÓL megközelítve ────────────
        print("\n=== HOLTJÁTÉK ===")
        print("Ugyanarra a pulzusra állunk, egyszer alulról, egyszer felülről közelítve.")
        print("Ha a két helyzet eltér, az a fogaskerekek hézaga — ez az, ami miatt a")
        print("gesztusok után a kamera nem pontosan oda áll vissza, ahonnan indult.")
        kiteres = min(10 * ms_per_deg, (felso - also) / 4)
        tarts(t.centre_ms - kiteres, "elmegyünk EGYIK oldalra")
        tarts(t.centre_ms, "vissza a középre — ALULRÓL érkezve. Jelöld meg.")
        tarts(t.centre_ms + kiteres, "elmegyünk a MÁSIK oldalra")
        tarts(t.centre_ms, "vissza a középre — FELÜLRŐL érkezve. Mérd meg az eltérést.")
        holtjatek = _szam("   Hány FOK a két 'közép' közti eltérés? (0, ha nincs) ")

        # ── összefoglaló ────────────────────────────────────────────────────────
        print("\n" + "=" * 66)
        print(f"MÉRT ÉRTÉKEK ({args.channel}):")
        print(f"  ms_per_deg = {ms_per_deg:.4f}")
        print(f"  min_ms     = {also:.2f}")
        print(f"  max_ms     = {felso:.2f}")
        print(f"  hatótáv    = +{(felso - t.centre_ms) / ms_per_deg:.0f} / "
              f"-{(t.centre_ms - also) / ms_per_deg:.0f} fok a középtől")
        print("               (ASZIMMETRIKUS, ha a közép nincs a sáv közepén — a pané nincs)")
        if holtjatek is not None:
            print(f"  holtjáték  = {holtjatek:.1f} fok")
        print("\nKipróbálni ELŐBB env-ből, a settings.py bántása nélkül:")
        elonev = f"FREEDROID_CAMERA_{args.channel.upper()}"
        print(f"  {elonev}_MS_PER_DEG={ms_per_deg:.4f} \\")
        print(f"  FREEDROID_CAMERA_MIN_MS={also:.2f} FREEDROID_CAMERA_MAX_MS={felso:.2f} \\")
        if holtjatek:
            print(f"  {elonev}_BACKLASH_DEG={holtjatek:.1f} \\")
        print(f"  .venv/bin/python scripts/servo_test.py --channel {args.channel} --range 0.15")
        print("=" * 66)
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        # Mindig: egy félbeszakadt mérés se hagyjon feszülő szervót a végállásban.
        pca.deinit()
        i2c.deinit()


if __name__ == "__main__":
    raise SystemExit(main())
