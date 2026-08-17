#!/usr/bin/env python3
"""A menetidő kalibrálása — `cm_per_s_at_full` és `deg_per_s_at_full`.

Ez a KÉT szám, amit a `settings.py` becslésként tartalmaz: a `move 2` és a `turn 90`
menetideje ezekből számol. A robot IRÁNYA és a MEGÁLLÁSA nem ezeken múlik (azok mérve
vannak), tehát egy rossz kalibráció pontatlan utat okoz, nem veszélyes robotot.

A mérés a VALÓDI vezérlőt hajtja (`CytronMotionController`), nem egy külön menetet:
így nem csak a számot méri, hanem azt is, hogy a menetidő-számítás, a leállás és a
watchdog együtt jól működik-e. A watchdog VÉGIG FUT — ha megállít, a mérés érvénytelen,
és ezt a script megmondja, ahelyett hogy egy rövidebb utat kalibrációnak hinne.

Futtatás a roboton, PADLÓN (nem felpolcolva — felpolcolt lánctalp nem tesz meg utat):

    cd /opt/free-droid/robot
    uv run python scripts/calibrate_motion.py                 # 1 m + 360 fok
    uv run python scripts/calibrate_motion.py --meters 2      # hosszabb út, pontosabb
    uv run python scripts/calibrate_motion.py --skip-turn

Kell hozzá: mérőszalag, és legalább `--meters` + 1 m szabad hely a robot ELŐTT.
"""

from __future__ import annotations

import argparse
from dataclasses import replace

from freedroid.config.settings import MotionSettings, load_settings
from freedroid.motion import CytronMotionController
from freedroid.motion.types import Direction, TurnDir
from freedroid.safety import UltrasonicWatchdog


def _szam_bekeres(kerdes: str) -> float | None:
    """Számot kér az operátortól. Üres/érvénytelen/EOF válasz -> None (kihagyjuk).

    Az EOF (Ctrl+D, vagy TTY nélküli futtatás) itt kihagyást jelent. A MEGERŐSÍTŐ
    kérdésnél SZÁNDÉKOSAN nincs ilyen kezelés: ott az EOF megszakítja a futást,
    mielőtt a robot elindulna — egy TTY nélküli környezetben nincs, aki azt mondja,
    hogy szabad az út, tehát ott a leállás a helyes válasz, nem a folytatás.
    """
    try:
        valasz = input(kerdes).strip().replace(",", ".")
    except EOFError:
        return None
    if not valasz:
        return None
    try:
        return float(valasz)
    except ValueError:
        print(f"  '{valasz}' nem szám — a lépést kihagyom.")
        return None


# A képlet KIS SZÖGRE érvényes (theta ~ 2*oldal/hossz). Negyed úthossznyi elsodródás
# már ~28 fokos elfordulás: ott a közelítés nem áll, a kapott arány értelmetlen, és
# elég extrém adatnál a nevező (hossz^2 + oldal*nyomtáv) nullához is tarthat. Ilyenkor
# nem "óvatosan számolunk", hanem NEM számolunk — rövidebb úton kell újramérni.
MAX_ELSODRODAS_ARANY = 0.25


def _trim(cfg: MotionSettings, hossz_cm: float,
          oldal_cm: float) -> tuple[float, float] | None:
    """Új oldalankénti trim az elsodródásból, vagy None, ha nem számolható.

    `oldal_cm` > 0 = balra húzott.

    A geometria: `hossz_cm` út alatt `oldal_cm` oldalirányú eltérés kis szögnél
    theta ~ 2*oldal/hossz szögelfordulást jelent, amit a két lánctalp úthossz-
    különbsége okoz: s_jobb - s_bal = theta * nyomtáv. Innen az arányuk:

        s_bal / s_jobb = (hossz^2 - oldal*nyomtáv) / (hossz^2 + oldal*nyomtáv)

    A LASSABB oldalhoz igazítunk (a gyorsabbat fogjuk vissza), mert teljes
    kitöltésen már nincs hová gyorsítani. Végül visszanormáljuk, hogy a gyorsabb
    oldal 1.0 legyen — különben minden kör lassítaná a robotot.
    """
    # A nevező (hossz^2 + oldal*nyomtáv) elvben nullára vagy negatívra futhat. Nem
    # algebrai ellenőrzést teszünk elé, hanem FIZIKAIT: a robot legalább a saját
    # nyomtávjánál hosszabb utat tegyen meg, különben nincs mit egyenességnek nevezni.
    # Ez egyben BIZONYÍTHATÓAN elég: hossz > nyomtáv és |oldal| <= hossz/4 mellett
    # |oldal*nyomtáv| < hossz^2, tehát a nevező és a számláló is szigorúan pozitív.
    if hossz_cm <= cfg.track_width_cm:
        return None
    if abs(oldal_cm) > MAX_ELSODRODAS_ARANY * hossz_cm:
        return None

    q = oldal_cm * cfg.track_width_cm
    arany = (hossz_cm**2 - q) / (hossz_cm**2 + q)

    bal, jobb = cfg.left_duty_trim, cfg.right_duty_trim
    if arany < 1.0:
        jobb *= arany       # balra húz -> a jobb oldal a gyorsabb
    else:
        bal /= arany        # jobbra húz -> a bal oldal a gyorsabb
    legnagyobb = max(bal, jobb)
    return bal / legnagyobb, jobb / legnagyobb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meters", type=float, default=1.0,
                    help="mekkora utat parancsoljunk (m). Hosszabb út = pontosabb arány")
    ap.add_argument("--degrees", type=float, default=360.0,
                    help="mekkora fordulást parancsoljunk (fok)")
    ap.add_argument("--skip-turn", action="store_true", help="csak a távolságot mérjük")
    ap.add_argument("--track-width", type=float, default=None,
                    help="a két lánctalp KÖZÉPVONALÁNAK távolsága cm-ben (mérőszalaggal, "
                         "egyszer). Az egyenesség-trim egyetlen ismeretlene.")
    args = ap.parse_args()
    if args.meters <= 0 or (not args.skip_turn and args.degrees <= 0):
        # Rögtön a beolvasás után, MINDEN kiírás és hardver-nyitás előtt: a `--degrees 0`
        # egyébként lefuttatna egy értelmetlen menetet, és csak a mérés VÉGÉN osztana
        # nullával — miután a robot már mozgott.
        ap.error("--meters (és --skip-turn nélkül --degrees is) nagyobb kell legyen nullánál")

    cfg = load_settings().motion
    if args.track_width is not None:
        cfg = replace(cfg, track_width_cm=args.track_width)
    else:
        print(f"ℹ️  Nyomtáv a configból: {cfg.track_width_cm:.0f} cm "
              f"(--track-width felülírja).")
    print(f"Jelenlegi (BECSÜLT) értékek: cm_per_s_at_full={cfg.cm_per_s_at_full}, "
          f"deg_per_s_at_full={cfg.deg_per_s_at_full}")
    print(f"Menet-kitöltés: {cfg.default_speed:.0%}\n")

    motion = CytronMotionController()
    watchdog = None
    megallitasok: list[str] = []

    def akadaly() -> None:
        # A watchdog szálából hívjuk: előbb megállítunk, aztán jegyzünk.
        motion.stop()
        megallitasok.append("stop")

    eredmenyek: dict[str, float] = {}
    try:
        # A watchdog létrehozása a try-on BELÜL: ha itt száll el (pl. foglalt GPIO),
        # a `motion` már nyitva van, és a lábai lefoglalva maradnának — a KÖVETKEZŐ
        # futás hasalna el tőle, egy egészen máshová mutató hibaüzenettel.
        watchdog = UltrasonicWatchdog(
            on_obstacle=akadaly,
            heading_source=lambda: (motion.heading, motion.is_turning),
        )
        watchdog.start()

        # --- 1. Távolság ---
        print(f"1. TÁVOLSÁG — a robot {args.meters} métert fog PARANCSRA megtenni.")
        print(f"   Kell: {args.meters + 1:.0f} m szabad hely előtte, és egy jelölés a "
              f"jelenlegi helyzeténél (ragasztószalag a padlóra).")
        input("   ENTER, ha a robot a padlón áll és szabad az út... ")

        megallitasok.clear()
        motion.move(direction=Direction.FORWARD, distance=args.meters)
        # AZONNAL rögzítjük, a beolvasás ELŐTT. A watchdog ugyanis tovább fut, amíg az
        # operátor mér és gépel: a robot ilyenkor ÁLL, tehát `heading=None`, tehát a
        # fail-safe ág fut, tehát MINDKÉT szenzor figyel — egy fal a robot mögött
        # percekig termeli a megállításokat, és eldobná a JÓ mérést. (MÉRVE
        # 2026-08-17: pontosan ez történt, a 222 cm-es futás így veszett el.)
        megallt_menetben = bool(megallitasok)

        if megallt_menetben:
            print("   ⚠️  A WATCHDOG MEGÁLLÍTOTT — a robot nem tette meg a teljes utat.\n"
                  "       A menetidő (cm_per_s) ebből NEM számolható, az EGYENESSÉG igen:\n"
                  "       ahhoz a ténylegesen megtett út és az oldalirányú elsodródás kell.")

        mert = _szam_bekeres("   Mért TÉNYLEGES előrehaladás (cm): ")
        oldal = _szam_bekeres("   Oldalirányú elsodródás (cm; BALRA = +, JOBBRA = -): ")

        if mert is not None and mert > 0 and not megallt_menetben:
            # t = várt_cm / (c_régi * duty), és a tényleges út = c_valódi * duty * t,
            # amiből a duty és a t kiesik: c_valódi = c_régi * tényleges / várt.
            vart_cm = args.meters * 100.0
            eredmenyek["cm_per_s_at_full"] = cfg.cm_per_s_at_full * (mert / vart_cm)
            print(f"   Várt {vart_cm:.0f} cm, mért {mert:.0f} cm ({mert / vart_cm:.0%}).")

        # `is not None`, nem `if oldal`: a beírt 0 azt jelenti, hogy EGYENESEN ment, és
        # azt ki KELL írni — nem azért, mert a trim ilyenkor változik (nem változik:
        # a 0 elsodródásra a képlet a MOSTANI értékeket adja vissza), hanem hogy az
        # operátor lássa, MELYIK értékekkel sikerült. A 0-t csendben elejteni azt
        # üzenné, hogy a sikeres futásból nem jött ki semmi.
        if mert is not None and mert > 0 and oldal is not None:
            uj = _trim(cfg, hossz_cm=mert, oldal_cm=oldal)
            if uj is None:
                print(f"   ⚠️  {abs(oldal):.0f} cm elsodródás {mert:.0f} cm alatt — ez már "
                      f"nem kis szög,\n       a képlet nem érvényes rá. Mérd újra RÖVIDEBB "
                      f"úton (--meters 0.5).")
            else:
                eredmenyek["left_duty_trim"], eredmenyek["right_duty_trim"] = uj
                merre = "balra" if oldal > 0 else "jobbra" if oldal < 0 else "sehova"
                print(f"   {mert:.0f} cm alatt {abs(oldal):.0f} cm-t húzott {merre} "
                      f"(nyomtáv {cfg.track_width_cm:.0f} cm).")

        # --- 2. Fordulás ---
        if not args.skip_turn:
            print(f"\n2. FORDULÁS — a robot {args.degrees:.0f} fokot fog PARANCSRA fordulni.")
            print("   Jelöld meg, merre néz most (pl. szalag a padlón az orra irányában).")
            input("   ENTER, ha kész... ")

            megallitasok.clear()
            motion.turn(direction=TurnDir.LEFT, degrees=args.degrees)
            # Fordulás közben a watchdog SZÁNDÉKOSAN nem állít meg (a súrolt ívet egyik
            # szenzor sem látja), tehát itt nincs értelme érvénytelenséget vizsgálni.

            mert_fok = _szam_bekeres(f"   Mennyit fordult TÉNYLEGESEN (fok, "
                                     f"a parancsolt {args.degrees:.0f} helyett): ")
            if mert_fok is not None and mert_fok > 0:
                eredmenyek["deg_per_s_at_full"] = (
                    cfg.deg_per_s_at_full * (mert_fok / args.degrees))
                print(f"   Parancsolt {args.degrees:.0f}°, mért {mert_fok:.0f}° "
                      f"({mert_fok / args.degrees:.0%}).")

    except KeyboardInterrupt:
        print("\nMegszakítva.")
        return 130
    except EOFError:
        # A megerősítő kérdéseknél EOF = nincs, aki azt mondja, hogy szabad az út.
        # A leállás a helyes válasz; itt csak azt intézzük el, hogy ne nyers stack
        # trace legyen belőle. EGY helyen, mert mindkét megerősítés ide fut be.
        print("\n❌ Nem interaktív környezet (EOF) — a mérés megszakadt.\n"
              "   A robot nem indult el, illetve megállt.")
        return 1
    finally:
        # SORREND: előbb a motorok állnak le, csak utána engedjük el a watchdogot.
        motion.close()
        if watchdog is not None:
            watchdog.close()

    if not eredmenyek:
        print("\nNem született használható érték.")
        return 1

    print("\n" + "=" * 68)
    print("Írd be ezeket a robot/src/freedroid/config/settings.py MotionSettings-be:")
    for kulcs, ertek in eredmenyek.items():
        # A trim századokon múlik (3% eltérés 2 m alatt fél métert visz) — ott több
        # tizedes kell, mint a menetidőnél.
        print(f"    {kulcs}: float = {ertek:.3f}" if "trim" in kulcs
              else f"    {kulcs}: float = {ertek:.1f}")
    print("=" * 68)
    print("Utána FUTTASD ÚJRA: a robotnak most már a parancsolt utat kell megtennie.\n"
          "Ha másodszorra is elcsúszik, a duty->sebesség viszony nem lineáris\n"
          "(holtsáv alacsony kitöltésnél) — akkor a menet-kitöltésnél kell kalibrálni.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
