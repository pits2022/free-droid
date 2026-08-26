#!/usr/bin/env python3
"""Phase 4 mérés — a watchdog mint EGÉSZ: az akadály megjelenésétől a megállásig.

MIÉRT NEM ELÉG A `watchdog_latency.py`. Az a NYERS busy-wait ciklust méri: egyetlen
`gpio_read` lépésközét. Kiváló szám, de nem az, ami a robotot megállítja. A veszélyes
mennyiség a TELJES reakcióidő, és abban négy tag van, amiből hármat az a script meg sem
érint: a 20 Hz-re TERVEZETT ciklus valódi üteme, a `min(3)` háromszoros mérése, MINDKÉT
szenzor lekérdezése körönként, és maga a `stop()`.

A LÁNC, és hogy melyik tagot mivel mérjük:

    akadály megjelenik        NEM megfigyelhető (nincs független műszerünk a szenzoron
                              kívül), ezért FELSŐ KORLÁTTAL számolunk: legrosszabb
                              esetben épp lekéstük a most induló mérést -> egy teljes
                              ciklusidő telik el, mire egyáltalán ránézünk
    a következő kör elindul   `korok` — a ciklus-kezdetek közti idő eloszlása
    megszületik a döntés      `korok` — egy kör HOSSZA (2 szenzor x min(3) mérés)
    lefut a `stop()`          `stop_idok` — a valódi megállító hívása, terhelés alatt
    a robot ténylegesen megáll   CSAK élesben: `--live-motion` (a tehetetlenség és a
                              lánctalp csúszása szoftverből nem látszik)

Így a felső korlát:  T = max(ciklusidő) + max(kör hossza) + max(stop) — a három tag
KÜLÖNBÖZŐ körökből való, tehát nem duplán számol.

Terhelés: ugyanaz az ollama-futás, amit a `watchdog_latency.py` használ (a hű
munkaterhelés: memória-sávszélességet is eszik, nem csak magot).

    uv run python scripts/watchdog_e2e.py                  # időzítés, motor NEM forog
    uv run python scripts/watchdog_e2e.py --live-motion    # + valódi menet az akadálynak
"""

from __future__ import annotations

import argparse
import math
import signal
import statistics
import sys
import time

import watchdog_latency as WL

from freedroid.config.settings import load_settings
from freedroid.motion import CytronMotionController
from freedroid.motion.types import SPEED_DUTY, Direction, Speed
from freedroid.safety import FRONT, UltrasonicWatchdog


class MertWatchdog(UltrasonicWatchdog):
    """A VALÓDI watchdog, csak időbélyegzővel — nem egy másolat belőle.

    A mérés tárgya a szállított kód viselkedése, tehát a mérőnek is azt kell futtatnia:
    egy újraírt mérőciklus a saját ütemét mérné, nem a robotét.

    A `list.append()` itt SZÁNDÉKOSAN megengedett, szemben a `watchdog_latency.py`
    fix-hisztogramos ciklusával. Ott mikroszekundumos lépésközöket mértünk, és az
    allokáció maga lett a mért tüske; itt körönként EGY append van, 20 Hz-en — a
    ciklusidő öt nagyságrenddel nagyobb, mint a lista bővítése.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # (kezdet, vég, az adott körben mért távolságok)
        self.korok: list[tuple[float, float, dict[str, float | None]]] = []

    def poll_once(self) -> None:
        t0 = time.perf_counter()
        try:
            super().poll_once()
        finally:
            # `finally`: egy hibázó kör is KÖR — pont az a leglassabb (időtúllépések),
            # és ha kimaradna a mintából, a farok eltűnne a statisztikából.
            self.korok.append((t0, time.perf_counter(), self.distances_cm()))


class Fek:
    """A watchdog `on_obstacle` callbackje: a VALÓDI `stop()`-ot hívja, idővel körítve."""

    def __init__(self, motion: CytronMotionController) -> None:
        self._motion = motion
        self.esemenyek: list[tuple[float, float]] = []

    def __call__(self) -> None:
        t0 = time.perf_counter()
        try:
            self._motion.stop()
        finally:
            self.esemenyek.append((t0, time.perf_counter()))


def _q(minta: list[float], q: float) -> float:
    """Kvantilis rendezett mintából. Kis elemszám (pár száz kör) — nincs mit optimalizálni."""
    if not minta:
        return float("nan")
    rendezett = sorted(minta)
    i = min(int(q * len(rendezett)), len(rendezett) - 1)
    return rendezett[i]


def _kiir_ms(cimke: str, minta: list[float]) -> None:
    if not minta:
        print(f"  {cimke:<24} — nincs minta")
        return
    print(f"  {cimke:<24} medián {statistics.median(minta)*1e3:7.1f} ms   "
          f"p95 {_q(minta, 0.95)*1e3:7.1f} ms   MAX {max(minta)*1e3:7.1f} ms   "
          f"(n={len(minta)})")


def _stop_ido(motion: CytronMotionController, db: int) -> list[float]:
    """A `stop()` önmagában, terhelés alatt.

    Külön mérjük, és nem a valódi akadály-eseményekből: a `stop()` idempotens és
    mozgás nélkül is ugyanazt a két PWM-írást végzi, tehát mérhető operátor és akadály
    nélkül. Az akadályhoz kötött mérés csak akkor adna mintát, ha valaki a szenzor előtt
    tartja a kezét a mérés felében — egy műszer ne függjön ettől.
    """
    idok = []
    for _ in range(db):
        t0 = time.perf_counter()
        motion.stop()
        idok.append(time.perf_counter() - t0)
        time.sleep(0.01)
    return idok


def _idozites(wd: MertWatchdog, motion: CytronMotionController,
              masodperc: float) -> tuple[list[float], list[float], list[float]]:
    wd.korok.clear()
    wd.start()
    time.sleep(masodperc)
    stop_idok = _stop_ido(motion, db=50)
    wd.stop_monitoring()

    korok = wd.korok
    hossz = [v - k for k, v, _ in korok]
    ciklus = [b[0] - a[0] for a, b in zip(korok, korok[1:])]
    return ciklus, hossz, stop_idok


def _kiir_kozelites(wd: MertWatchdog, t0: float, v_cm_s: float, db: int = 8) -> None:
    """A megállítás előtti utolsó körök elülső mérései.

    EGYENES közelítésnél a lépés körönként ~v * ciklusidő (slow-on ~4 cm). Ha a
    lépések ugrálnak vagy nőnek, a robot nem az akadály felé ment — pontosan az a
    hiba, amit a végén a negatív reakcióidő elárul, csak itt LÁTHATÓ is.
    """
    nyom = [(t, tav.get(FRONT)) for t, _v, tav in wd.korok][-db:]
    if not nyom:
        return
    print("  a közelítés nyoma (front, a menet kezdetétől):")
    elozo = None
    for t, cm in nyom:
        szoveg = "néma" if cm is None else f"{cm:7.1f} cm"
        lepes = "" if elozo is None or cm is None else f"   lépés {elozo - cm:+5.1f} cm"
        print(f"    {t - t0:5.2f} s  {szoveg}{lepes}")
        elozo = cm
    print(f"    (egyenes közelítésnél a várható lépés ~{v_cm_s * 0.21:.1f} cm/kör)")


def _live(wd: MertWatchdog, motion: CytronMotionController, fek: Fek,
          tavolsag_m: float, speed: Speed, kuszob_cm: float, keresen: bool) -> int:
    cfg = load_settings().motion
    v_cm_s = cfg.cm_per_s_at_full * SPEED_DUTY[speed]

    print(f"\n=== ÉLES MENET === {speed.value} ({v_cm_s:.0f} cm/s), "
          f"deadman {tavolsag_m:.2f} m")
    print("  Tegyél akadályt a robot ELÉ, kb. 70-100 cm-re. A watchdognak kell")
    print("  megállítania — a megtett út deadmanje viszont a parancsba adott távolság,")
    print("  tehát egy HALOTT watchdog mellett is megáll ennyi után.")
    if keresen:
        input("  ENTER, ha az út szabad és az akadály a helyén van (Ctrl-C = mégsem): ")

    # A visszaszámlálás `--yes` mellett is megmarad: az elrettentés nem a kérdés, hanem
    # a három másodperc, amíg a robot még elkapható.
    for i in (3, 2, 1):
        print(f"  {i}...")
        time.sleep(1.0)

    fek.esemenyek.clear()
    wd.korok.clear()          # a nyom CSAK a menetről szóljon, ne az időzítés-mérésről
    wd.start()
    t0 = time.perf_counter()
    motion.move(direction=Direction.FORWARD, distance=tavolsag_m, speed=speed)
    t_vissza = time.perf_counter()
    wd.stop_monitoring()

    if not fek.esemenyek:
        print("\n  🔴 A WATCHDOG NEM ÁLLÍTOTTA MEG a robotot — a menet a deadmanen ért véget")
        print(f"     ({t_vissza - t0:.2f} s). Vagy nem ért akadályhoz, vagy a védelem néma.")
        print(f"     Utolsó mérések: {wd.distances_cm()}")
        return 1

    t_stop = fek.esemenyek[0][0]
    print(f"\n  megállítva {t_stop - t0:.2f} s-nál, a `move()` {t_vissza - t0:.2f} s-nál "
          f"adta vissza a vezérlést")
    print(f"    (a kettő különbsége = a `stop()` és a menet-hurok bontása: "
          f"{(t_vissza - t_stop)*1e3:.0f} ms)")
    print(f"  a megállítás pillanatában mért távolságok: {wd.distances_cm()}")
    _kiir_kozelites(wd, t0, v_cm_s)

    # A megállás UTÁNI hézag. Külön kör kell hozzá: a fenti szám a döntés pillanatáé,
    # a robot pedig a tehetetlenségével még csúszik valamennyit.
    time.sleep(0.5)
    utolagos = []
    for _ in range(3):
        wd.poll_once()
        utolagos.append(wd.distances_cm().get(FRONT))
    ervenyes = [v for v in utolagos if v is not None and math.isfinite(v)]
    hezag = statistics.median(ervenyes) if ervenyes else None
    if len(ervenyes) > 1:
        print(f"  a megállás utáni három mérés: "
              f"{', '.join(f'{v:.1f}' for v in ervenyes)} cm")
    if hezag is None:  # néma szenzor, vagy üres tér mindhárom körben
        print(f"  ⚠️ a megállás utáni hézag nem mérhető ({utolagos}) — mérőszalaggal ellenőrizd")
        return 0

    print(f"  MEGÁLLÁS UTÁNI HÉZAG: {hezag:.1f} cm  (a küszöb {kuszob_cm:.0f} cm)")

    if hezag > kuszob_cm:
        # FIZIKAILAG LEHETETLEN egyenes közelítésnél: a döntés a küszöb ALATT született,
        # a robot pedig előre ment. Ha a megállás után NAGYOBB a hézag, akkor a két mérés
        # nem ugyanazt a pontot nézte — a robot elfordult (a trim alacsony kitöltésen
        # nem tartja az irányt), és az akadály kicsúszott az ultrahang kúpjából, ami
        # mögötte a KÖVETKEZŐ felületet méri. A reakcióidőt ilyenkor NEM számoljuk ki:
        # egy negatív ms-szám nem "gyorsabb a fénynél", hanem érvénytelen mérés, és a
        # műszer dolga ezt kimondani, nem lenyelni.
        print("  ⚠️ ÉRVÉNYTELEN MÉRÉS: a megállás utáni hézag NAGYOBB, mint a döntéskori.")
        print("     A robot nem egyenesen közelített (elfordult), vagy az akadály")
        print("     kicsúszott a szenzor kúpjából. ISMÉTELD MEG — a fékút ebből nem jön ki.")
        return 0

    befutas = kuszob_cm - hezag
    print(f"  a küszöbön TÚL megtett út: {befutas:.1f} cm  ->  reakcióidő "
          f"{befutas / v_cm_s * 1e3:.0f} ms  ({v_cm_s:.0f} cm/s mellett)")
    print("  ⚠️ Ez a szenzor száma. Mérőszalaggal is nézd meg: egy ferde vagy puha")
    print("     akadályt az ultrahang MÁSHOL lát, mint ahol van.")
    if hezag <= 0:
        print("  🔴 NEKIMENT.")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=20.0,
                    help="időzítés-mérés ablaka feltételenként (alap: 20)")
    ap.add_argument("--load", choices=("ollama", "stress", "none"), default="ollama",
                    help="mivel terheljünk (alap: ollama = a valós munkaterhelés)")
    ap.add_argument("--model", default="csaba_ajtony/szabi-3b-v12",
                    help="ollama modell a terheléshez (a demó edge-modellje)")
    ap.add_argument("--live-motion", action="store_true",
                    help="VALÓDI MENET egy akadálynak. A motorok forognak!")
    ap.add_argument("--distance", type=float, default=1.0,
                    help="a menet deadman-távolsága méterben (alap: 1.0)")
    ap.add_argument("--speed", choices=[s.value for s in Speed], default=Speed.SLOW.value,
                    help="menet-sebesség (alap: slow — először a leglassabb)")
    ap.add_argument("--yes", action="store_true",
                    help="a menet ENTER-es megerősítése nélkül (terminál nélküli futáshoz)")
    args = ap.parse_args()

    # ELÖL, nem a menetnél: a megerősítés az időzítés-mérés UTÁN jönne, tehát terminál
    # nélkül a futás két perc mérés után hasalt el EOFError-ral (mérve 2026-08-26, a
    # Claude Code `!` prefixe nem ad TTY-t). Egy előfeltételt az elején kell megnézni.
    if args.live_motion and not args.yes and not sys.stdin.isatty():
        print("nincs terminál (a megerősítést nem lehet bekérni) — vagy valódi "
              "terminálból indítsd, vagy add hozzá a --yes kapcsolót", file=sys.stderr)
        return 2

    cfg = load_settings()
    kuszob = cfg.safety.stop_threshold_cm

    # SIGTERM is a `finally`-n keresztül menjen: enélkül egy `kill` forgó lánctalpat hagy.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    motion = CytronMotionController()
    fek = Fek(motion)
    wd = MertWatchdog(on_obstacle=fek,
                      heading_source=lambda: (motion.heading, motion.is_turning))
    terheles = None
    try:
        print(f"küszöb {kuszob:.0f} cm, tervezett ciklus "
              f"{cfg.safety.poll_interval_s*1e3:.0f} ms "
              f"({1/cfg.safety.poll_interval_s:.0f} Hz)")

        print("\n--- ÜRESJÁRAT (alapvonal) ---")
        ciklus_a, hossz_a, stop_a = _idozites(wd, motion, args.seconds)
        _kiir_ms("ciklusidő", ciklus_a)
        _kiir_ms("egy kör hossza", hossz_a)
        _kiir_ms("stop()", stop_a)

        ciklus, hossz, stop_idok = ciklus_a, hossz_a, stop_a
        if args.load != "none":
            terheles = WL.terheles_indit(args.load, args.model)
            WL.felfutas_bevar()
            print(f"\n--- TERHELÉS ALATT ({args.load}) ---")
            ciklus, hossz, stop_idok = _idozites(wd, motion, args.seconds)
            _kiir_ms("ciklusidő", ciklus)
            _kiir_ms("egy kör hossza", hossz)
            _kiir_ms("stop()", stop_idok)

        if not ciklus:
            print("\n🔴 egyetlen teljes kör sem futott le — a mérés érvénytelen")
            return 1

        t_felso = max(ciklus) + max(hossz) + max(stop_idok)
        print("\n=== A FELSŐ KORLÁT ===")
        print(f"  T = max(ciklus) {max(ciklus)*1e3:.0f} ms + max(kör) {max(hossz)*1e3:.0f} ms"
              f" + max(stop) {max(stop_idok)*1e3:.1f} ms = {t_felso*1e3:.0f} ms")
        for speed in Speed:
            v = cfg.motion.cm_per_s_at_full * SPEED_DUTY[speed]
            ut = v * t_felso
            jel = "OK " if ut < kuszob else "🔴 "
            print(f"  {jel}{speed.value:<7} {v:5.1f} cm/s -> a döntésig megtett út "
                  f"{ut:5.1f} cm   (küszöb {kuszob:.0f} cm)")
        print("  A megtett út a küszöbBŐL fogy: ami marad, az a fékút + a tartalék.")
        print("  A tehetetlenség ebben NINCS benne — azt csak a --live-motion mutatja meg.")

        kod = 0
        if args.live_motion:
            kod = _live(wd, motion, fek, args.distance, Speed(args.speed), kuszob,
                        keresen=not args.yes)
        else:
            print("\n(A valódi fékút méréséhez: --live-motion)")
        return kod
    except KeyboardInterrupt:
        return 130
    finally:
        WL.terheles_leall(terheles)
        wd.close()
        motion.close()


if __name__ == "__main__":
    raise SystemExit(main())
