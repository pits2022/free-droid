#!/usr/bin/env python3
"""Phase 1.5 mérés — bírja-e a Python busy-wait watchdog a valós CPU-terhelést?

MIÉRT EZ A LEGFONTOSABB MÉRÉS A LISTÁN. A biztonsági watchdog HC-SR04 impulzus-
szélességet mér egy szoros Python ciklussal. Üresjáratban ez ±3 µs (mérve
2026-08-14). A watchdognak viszont AKKOR kell működnie, amikor a 3B modell
inferál a Pi-n — és a hiba IRÁNYA a rossz:

    a ciklus kimarad  ->  a lefutó él későn látszik  ->  HOSSZABB impulzus
                      ->  NAGYOBB távolság          ->  "szabad az út"

Vagyis terhelés alatt a robot pont akkor hiszi szabadnak az utat, amikor nem az.
Ez az egyetlen hibánk, ami FIZIKAI kárt okoz; a többi legrosszabb esetben ronda demó.

A DÖNTŐ SZÁM. Egy `G` másodperces kihagyás a mérőciklusban G * 17150 cm
távolság-túlbecslést okoz (a hang 34300 cm/s, oda-vissza út). A `stop_threshold_cm`
25 cm, tehát egy 20 cm-es akadályt 25 cm fölé tolni +5 cm-t igényel:

    G = 5 / 17150 = 291 µs

Egyetlen 0,3 ms-os ütemezési kimaradás elég. Egy Linux ütemezési kvantum
1-10 ms. A mérés tehát nem "vajon", hanem "mennyivel".

    uv run python scripts/watchdog_latency.py                    # ollama-terhelés
    uv run python scripts/watchdog_latency.py --load stress      # szintetikus
    uv run python scripts/watchdog_latency.py --load none        # csak alapvonal
"""

from __future__ import annotations

import argparse
import gc
import os
import signal
import subprocess
import time

import _hw

from freedroid.config import gpio as G
from freedroid.config.settings import SafetySettings

SOUND_CM_PER_S = 34300.0
# A lépésköz-hisztogram 1 µs-os vödrökben, 0..20 ms; a fölötte lévő a túlcsordulás.
VODOR_DB = 20000
# Egy G másodperces kihagyás ennyi cm túlbecslést okoz (oda-vissza út miatt /2).
CM_PER_S_HIBA = SOUND_CM_PER_S / 2.0


def _gap_minta(lgpio, h, pin: int, masodperc: float) -> tuple[list[int], float, int]:
    """A mérőciklus lépésköz-eloszlása — pontosan az a ciklus, amit `_measure_cm` futtat.

    Szenzor NEM kell hozzá: a vizsgált mennyiség a Python + ütemező viselkedése,
    nem a szenzoré. Ezért ez a mérés akkor is érvényes, ha épp nincs bekötve panel.

    A MŰSZER NEM GYÁRTHATJA AZT A JELENSÉGET, AMIT MÉR. Az első változat minden
    lépésben `list.append()`-elt: 30 s alatt ~15 millió Python-float (~félgigányi
    memória), tehát a ciklusba beleépült egy `realloc` és a ciklikus GC — vagyis a
    mért TÜSKÉK egy része maga a mérőeszköz lehetett, nem az ütemező. Márpedig ennek
    a mérésnek pont a tüskék a tárgya.

    Ezért: FIX méretű hisztogram (1 µs-os vödrök), semmi allokáció a ciklusban, és a
    ciklikus GC kikapcsolva az ablak idejére. A maximumot külön, pontosan visszük.
    """
    hist = [0] * (VODOR_DB + 1)          # az utolsó vödör a túlcsordulás gyűjtője
    legnagyobb = 0.0
    n = 0
    gc.disable()
    try:
        veg = time.perf_counter() + masodperc
        elozo = time.perf_counter()
        while elozo < veg:
            lgpio.gpio_read(h, pin)
            most = time.perf_counter()
            gap = most - elozo
            us = int(gap * 1e6)
            hist[us if us < VODOR_DB else VODOR_DB] += 1
            if gap > legnagyobb:
                legnagyobb = gap
            n += 1
            elozo = most
    finally:
        gc.enable()
    return hist, legnagyobb, n


def _stat(minta: tuple[list[int], float, int], kuszob_cm: float) -> dict:
    hist, legnagyobb, n = minta

    def kvantilis(q: float) -> float:
        """Kumulatív hisztogramból, 1 µs felbontással — a farokhoz bőven elég."""
        cel, futo = q * n, 0
        for us, db in enumerate(hist):
            futo += db
            if futo >= cel:
                return float(us)
        return float(VODOR_DB)

    # Mekkora kihagyás kell ahhoz, hogy a küszöb-hibát okozza (lásd a modul-doksit)?
    veszelyes_gap = kuszob_cm / CM_PER_S_HIBA
    veszelyes_us = int(veszelyes_gap * 1e6)
    return {
        "n": n,
        "median_us": kvantilis(0.5),
        "p99_us": kvantilis(0.99),
        "p999_us": kvantilis(0.999),
        "max_us": legnagyobb * 1e6,
        "max_hiba_cm": legnagyobb * CM_PER_S_HIBA,
        "veszelyes_db": sum(hist[min(veszelyes_us, VODOR_DB):]),
        "veszelyes_gap_us": veszelyes_gap * 1e6,
    }


def _kiir(cimke: str, s: dict) -> None:
    print(f"\n--- {cimke} ---")
    print(f"  minták:            {s['n']}")
    print(f"  medián lépésköz:   {s['median_us']:9.1f} us")
    print(f"  p99:               {s['p99_us']:9.1f} us")
    print(f"  p99.9:             {s['p999_us']:9.1f} us")
    print(f"  LEGROSSZABB:       {s['max_us']:9.1f} us  ->  {s['max_hiba_cm']:.1f} cm "
          f"távolság-TÚLBECSLÉS")
    print(f"  a {s['veszelyes_gap_us']:.0f} us-os veszélyküszöböt elérő lépések: "
          f"{s['veszelyes_db']} db")


def terheles_indit(mod: str, model: str) -> subprocess.Popen | None:
    if mod == "none":
        return None
    if mod == "stress":
        print("terhelés: stress-ng --cpu 4")
        # SAJÁT FOLYAMATCSOPORT: a `stress-ng` négy worker-gyereket forkol, és a
        # főfolyamatnak küldött SIGTERM őket ÁRVÁN hagyná — a mérés után is terhelnék
        # a Pi-t, csendben meghamisítva minden következő mérést.
        return subprocess.Popen(["stress-ng", "--cpu", "4"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    # Az ollama a HŰ terhelés: ez fut majd élesben, és a memória-sávszélességet is
    # eszi, nem csak a magokat — a szintetikus CPU-pörgetés ezt alábecsüli.
    print(f"terhelés: ollama run {model}")
    # A bemelegítés NEM végzetes, ha kifut az időből: a 3B hidegen több percig is
    # tölthet, és a mérésnek nem a bemelegítés a tárgya. Ha elhasal, a háttérben
    # induló generálás úgyis betölti a modellt — csak tovább tart a felfutás, amit
    # lentebb MEGVÁRUNK (nem fix sleep).
    try:
        subprocess.run(["ollama", "run", model, "szia"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except subprocess.TimeoutExpired:
        print("  (a bemelegítés kifutott az időből — nem baj, a felfutást megvárjuk)")
    return subprocess.Popen(
        ["ollama", "run", model,
         "Sorold fel részletesen, mit csinálsz egy hosszú napon. Írj sokat."],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def terheles_leall(terheles: subprocess.Popen | None) -> None:
    """A TELJES folyamatcsoportot állítja le, nem csak a főfolyamatot.

    Kiemelve, mert a `watchdog_e2e.py` ugyanezt a terhelést indítja: a `stress-ng`
    árva worker-eiről szóló tanulság (lásd `terheles_indit`) két másolatban előbb-
    utóbb szétcsúszik, és az árván maradt terhelés MINDEN következő mérést csendben
    meghamisít.
    """
    if terheles is None:
        return
    try:
        os.killpg(os.getpgid(terheles.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        terheles.terminate()
    # És MEGVÁRJUK, hogy tényleg megszűnt-e. NEM a zombi miatt (azt a kilépő szülő után az
    # init learatja): enélkül a függvény akkor is visszatér, ha a terhelés MÉG FUT, és a
    # következő mérés ÜRESJÁRATI alapvonala lenne tőle hamis. Ugyanaz a hiba, amit az árva
    # stress-ng workereknél már kifizettünk. (PR #96 review.)
    try:
        terheles.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        terheles.kill()
        terheles.wait()


def _cpu_ido() -> tuple[float, float]:
    """(dolgozott, összes) jiffy a /proc/stat első sorából."""
    with open("/proc/stat") as f:
        mezok = [float(x) for x in f.readline().split()[1:]]
    ossz = sum(mezok)
    return ossz - mezok[3], ossz          # mezok[3] = idle


def felfutas_bevar(max_s: float = 240.0, kell: float = 0.5) -> bool:
    """Megvárja, amíg a terhelés TÉNYLEG fut — fix sleep helyett mért feltétel.

    Fix `sleep(3)`-mal a mérés elindulhat úgy, hogy a modell még TÖLT (lemez-I/O,
    nem CPU): az eredmény hamis "nincs baj" lenne, mert a terhelés még rá sem állt.

    A műszer /proc/stat-delta, NEM a load average. Az elsőre kézenfekvő `loadavg`
    egy EGYPERCES exponenciális átlag: percekig késik, tehát egy épp felfutó
    terhelést "nem fut"-nak lát — pont a rossz irányban téved (a mérés indulna
    tovább vagy sosem hitelesítenénk). Rossz időskálájú műszer volt, kicseréltem.
    """
    veg = time.perf_counter() + max_s
    d0, o0 = _cpu_ido()
    while time.perf_counter() < veg:
        time.sleep(1.0)
        d1, o1 = _cpu_ido()
        hasznalat = (d1 - d0) / (o1 - o0) if o1 > o0 else 0.0
        d0, o0 = d1, o1
        if hasznalat >= kell:
            print(f"  felfutott (CPU {hasznalat*100:.0f}%), mérés indul")
            return True
    print("  ⚠️ a terhelés NEM futott fel — a mérés így ÉRTELMETLEN, ne hidd el az eredményt")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=10.0,
                    help="mérési ablak feltételenként (alap: 10)")
    ap.add_argument("--load", choices=("ollama", "stress", "none"), default="ollama",
                    help="mivel terheljünk (alap: ollama = a valós munkaterhelés)")
    ap.add_argument("--model", default="szabi-3b", help="ollama modell a terheléshez")
    ap.add_argument("--threshold-cm", type=float, default=5.0,
                    help="mekkora távolság-hibát tekintünk veszélyesnek (alap: 5 cm — "
                         "ennyi tolja a 20 cm-es akadályt a 25 cm-es stop-küszöb fölé)")
    args = ap.parse_args()

    import lgpio

    h = _hw.open_gpiochip()
    echo = G.ULTRASONIC["front"]["echo"]
    terheles = None
    try:
        lgpio.gpio_claim_input(h, echo, lgpio.SET_PULL_DOWN)

        print(f"mérőciklus GPIO{echo}-n, {args.seconds:.0f} s feltételenként")
        alap = _gap_minta(lgpio, h, echo, args.seconds)
        _kiir("ÜRESJÁRAT (alapvonal)", _stat(alap, args.threshold_cm))

        if args.load != "none":
            terheles = terheles_indit(args.load, args.model)
            felfutas_bevar()
            terhelt = _gap_minta(lgpio, h, echo, args.seconds)
            _kiir(f"TERHELÉS ALATT ({args.load})", _stat(terhelt, args.threshold_cm))

            a, t = _stat(alap, args.threshold_cm), _stat(terhelt, args.threshold_cm)
            print("\n=== VERDIKT ===")
            if t["veszelyes_db"] == 0:
                print(f"  A legrosszabb kihagyás terhelés alatt {t['max_us']:.0f} us "
                      f"= {t['max_hiba_cm']:.1f} cm hiba, a {args.threshold_cm} cm-es")
                print("  büdzsé ALATT. A Python busy-wait EBBEN a felállásban elég.")
            else:
                # A "hány százaléka a ciklus-lépéseknek" ROSSZ NEVEZŐ: milliószám van
                # belőlük, tehát bármilyen valós kockázat 0,000%-nak látszik. A mérés
                # akkor ér valamit, ha a VESZÉLYT a MÉRÉSRE vetítjük: egy Echo-impulzus
                # a stop-küszöbnél ~1,5 ms hosszú, és a mérés akkor romlik el, ha ebbe
                # az ablakba esik egy kihagyás.
                rata = t["veszelyes_db"] / args.seconds
                # A SÉRÜLÉKENY ABLAK az Echo-impulzus hossza a STOP-KÜSZÖBNÉL — NEM a
                # hibabüdzséből számolva. (Az első változatom a `--threshold-cm`-et,
                # tehát az 5 cm-es büdzsét tette ide: ötszörös ALÁbecslés, és pont a
                # veszély irányában. A stop-küszöb és az ütemezés a settings-ből jön.)
                S = SafetySettings()
                impulzus_s = 2 * (S.stop_threshold_cm / 100.0) / 343.0
                per_meres = rata * impulzus_s
                print(f"  veszélyes kihagyás: {t['veszelyes_db']} db {args.seconds:.0f} s "
                      f"alatt = {rata:.1f}/s")
                print(f"  a legrosszabb: {t['max_us']:.0f} us = {t['max_hiba_cm']:.1f} cm "
                      f"TÚLBECSLÉS — 'szabad az út' irányba")
                print(f"  egy mérés eséllyel romlik el: {per_meres*100:.2f}%  "
                      f"(sérülékeny ablak: {impulzus_s*1000:.2f} ms = az Echo-impulzus "
                      f"{S.stop_threshold_cm:.0f} cm-nél)")
                if per_meres > 0:
                    hz = 1.0 / S.poll_interval_s
                    print(f"    -> {hz:.0f} Hz-es watchdognál ({S.poll_interval_s*1000:.0f} ms "
                          f"ciklus) ~{1/(per_meres*hz):.0f} másodpercenként EGY hamis "
                          f"'szabad az út'")
                    print(f"    -> HÁROM egymás utáni mérés min()-ével: "
                          f"{per_meres**3:.1e} (a hiba EGYIRÁNYÚ, tehát a min() kiszűri)")
                print("  A Python busy-wait ÖNMAGÁBAN nem elég. A hiba nem az átlagban van:")
                print(f"  a medián {t['median_us']:.1f} us (üresjáratban {a['median_us']:.1f}),")
                print("  vagyis egy átlag-alapú mérés ezt ELFEDNÉ.")
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        terheles_leall(terheles)
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    raise SystemExit(main())
