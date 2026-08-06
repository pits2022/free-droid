#!/usr/bin/env python3
"""Tool-MEGBÍZHATÓSÁG mérése verziókon át — objektíven, pontozó nélkül.

MIÉRT EZ A MÉRŐESZKÖZ: a tool-hívás az egyetlen dimenzió, amit gép is el tud dönteni
(lefut-e a parser, jó tool-e, jók-e az argumentumok). Nincs benne pontozói torzítás —
és épp az derült ki 2026-08-05-én, hogy a nem-vak emberi pontozás 24 pontot tévedett
bájtra azonos válaszokon.

MIÉRT ISMÉTLÉSSEL: temperature=0.7-nél a tool-hívás VALÓSZÍNŰSÉGI VÁLTOZÓ. A demónak
nem az kell, hogy a modell KÉPES legyen a helyes hívásra, hanem hogy MEGBÍZHATÓAN
adja. Ezért kérdésenként N futás VÁLTOZÓ seeddel, és a pontszám 0..N — nem pass/fail.

MIÉRT VÁLTOZÓ SEEDDEL — a pontos indok, mert az első nem stimmelt. Azt vártam, hogy
fix seeddel az ismétlés ugyanazt a választ adja, tehát az átlagolás látszatművelet
lenne. MÉRÉS (2026-08-05): az Ollama **fix seeddel sem reprodukálható** — két
egymást követő, seed=42-es hívás különböző választ adott ugyanarra a kérdésre.
Az ismétlés tehát fix seeddel is mérne valamit, csak vezérletlenül. A változó seed
SZÁNDÉKOSAN mintavételez a mintavételi eloszlásból, ahelyett hogy az Ollama
esetleges nem-determinizmusára támaszkodnánk. (Mellékesen ez teszi a
megbízhatóság-mérést szükségessé: ha a kimenet nem reprodukálható, akkor egyetlen
futás nem is jellemzi a modellt.)

PONTOZÁS
  POZITÍV kérdés: a parser legalább egy hívása illeszkedik a `varhato` egyikére
    (a név egyezik, ÉS a megadott args mind stimmel) ÉS nincs kitalált tool-név.
  NEGATÍV kérdés: nincs `tilos` nevű hívás ÉS nincs kitalált név.
  A KITALÁLT NÉV mindig bukás — a v8 8B `connect_to`-t, a 3B
  `disable_collision_sensor`-t gyártott, pont tiltott kérésre.

MIT NEM MÉR: a mondat minőségét, a personát, a magyarságot. Csak azt, hogy a robot
végrehajtaná-e a helyes műveletet. Fallbacknél ez az elsődleges kérdés.

    python tool_reliability.py --models szabi-3b-v8 szabi-3b-v11e1 --repeat 3
    python tool_reliability.py --models $(ollama list | awk '/szabi-3b/{print $1}') --repeat 3
    python tool_reliability.py --models szabi-3b-v11e1 --repeat 1 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot" / "src"))

from freedroid.tools.parser import KNOWN_TOOLS, parse_tools  # noqa: E402

from run_benchmark import BenchmarkError, GenerationTimeout, ollama_generate  # noqa: E402

KERDESEK = HERE / "tool_reliability.json"
SEED_BAZIS = 42


def _ossze(a, b) -> bool:
    """Érték-egyezés úgy, hogy a szám-alak ne számítson.

    A parser típusa tool-onként más: a `move` distance-e float (`2.0`), a `turn`
    degrees-e int (`90`). Nyers `str()`-rel egy JSON-beli `"distance": 2` SOHA nem
    illeszkedne (`"2.0" != "2"`), és a kérdés némán 0 pontot kapna — pont az a
    csendes félremérés, ami ellen ez a harness készült. Ma nincs szám-arg a
    kérdésekben, tehát a PR mért számait ez nem érinti; a csapda a következő
    kérdésnek szól.
    """
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def illeszkedik(hivasok, varhato: list[dict]) -> bool:
    """Van-e olyan hívás, ami a várt alakok VALAMELYIKÉRE illeszkedik.

    Az args részhalmaz-egyezés: a `varhato` args minden kulcsa stimmeljen; ami nincs
    megadva, az szabad. Így a `turn left 90` és a `turn left 85` is elfogadható, ha
    csak az irány a követelmény — de a `turn right 90` nem.
    """
    for h in hivasok:
        for v in varhato:
            if h.name != v["name"]:
                continue
            if all(_ossze(h.args.get(k), val) for k, val in v.get("args", {}).items()):
                return True
    return False


def ertekel(kerdes: dict, valasz: str) -> tuple[bool, str]:
    """(sikerült-e, rövid indok) — a parser a tolerans (futásidejű) módjában."""
    hivasok = parse_tools(valasz)
    kitalalt = [h.name for h in hivasok if h.name not in KNOWN_TOOLS]
    if kitalalt:
        return False, f"kitalált név: {','.join(sorted(set(kitalalt)))}"
    nevek = [h.name for h in hivasok]
    if kerdes["tipus"] == "negativ":
        tiltott = [n for n in nevek if n in kerdes["tilos"]]
        if tiltott:
            return False, f"tiltott hívás: {','.join(sorted(set(tiltott)))}"
        return True, ""
    if illeszkedik(hivasok, kerdes["varhato"]):
        return True, ""
    return False, (f"kapott: {','.join(nevek)}" if nevek else "nincs tool-hívás")


def futtat(models: list[str], kerdesek: list[dict], repeat: int,
           timeout: float) -> dict:
    """{modell: {kérdés_id: {"pont": int, "indokok": [...], "valaszok": [...]}}}"""
    ki: dict[str, dict] = {}
    for m in models:
        ki[m] = {}
        for i, k in enumerate(kerdesek, 1):
            pont, indokok, valaszok = 0, [], []
            for r in range(repeat):
                try:
                    v, _ = ollama_generate(m, k["kerdes"], timeout, seed=SEED_BAZIS + r)
                except GenerationTimeout as e:
                    v = f"⏱ {e}"
                jo, indok = ertekel(k, v)
                pont += jo
                valaszok.append(v)
                if indok:
                    indokok.append(indok)
            ki[m][k["id"]] = {"pont": pont, "indokok": indokok, "valaszok": valaszok}
            print(f"  [{m}] {i}/{len(kerdesek)} {k['id']}: {pont}/{repeat}", file=sys.stderr)
    return ki


def jelentes(models: list[str], kerdesek: list[dict], ki: dict, repeat: int) -> None:
    print(f"# Tool-megbízhatóság — {repeat} futás/kérdés, változó seed "
          f"({SEED_BAZIS}..{SEED_BAZIS + repeat - 1})\n")
    print("| Kérdés | típus | " + " | ".join(models) + " |")
    print("| :--- | :--- |" + " ---: |" * len(models))
    for k in kerdesek:
        jel = "neg" if k["tipus"] == "negativ" else ("mem" if k["memorizalt"] else "új")
        print(f"| {k['id']} | {jel} | " +
              " | ".join(str(ki[m][k['id']]["pont"]) for m in models) + " |")

    csoportok = {
        "ÖSSZESEN": kerdesek,
        "  ebből pozitív": [k for k in kerdesek if k["tipus"] == "pozitiv"],
        "  ebből negatív": [k for k in kerdesek if k["tipus"] == "negativ"],
        "  ebből memorizált": [k for k in kerdesek if k["memorizalt"]],
        "  ebből új": [k for k in kerdesek if not k["memorizalt"]],
    }
    print()
    for cim, csop in csoportok.items():
        max_p = len(csop) * repeat
        cells = []
        for m in models:
            p = sum(ki[m][k["id"]]["pont"] for k in csop)
            cells.append(f"**{p}/{max_p}** ({100 * p / max_p:.0f}%)" if cim == "ÖSSZESEN"
                         else f"{p}/{max_p}")
        print(f"| {cim} | | " + " | ".join(cells) + " |")

    print("\n## Leggyakoribb hibák\n")
    for m in models:
        c = Counter(i for q in ki[m].values() for i in q["indokok"])
        if c:
            print(f"- **{m}**: " + ", ".join(f"{i} ×{n}" for i, n in c.most_common(4)))

    print("\n## Olvasat\n")
    print(f"- {len(kerdesek)} kérdés × {repeat} ismétlés effektíve **n≈{len(kerdesek)} tétel**, "
          "kisebb tételenkénti zajjal — NEM n=" f"{len(kerdesek) * repeat}. Egy 1–2 pontos")
    print("  különbség két modell közt nem értelmes; egy 3+ pontos igen.")
    print("- A **negatív** kérdéseken a magas pont azt jelenti, hogy a modell NEM tüzelt "
          "fölöslegesen. E nélkül a teszt a kapkodást jutalmazná.")
    print("- A **memorizált** és az **új** részösszeg különbsége mutatja, mennyi ebből "
          "betanult reflex és mennyi általánosítás.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", required=True, metavar="MODELL")
    ap.add_argument("--repeat", type=int, default=3, metavar="N",
                    help="hány futás kérdésenként, változó seeddel (alap: 3)")
    ap.add_argument("--kerdesek", type=Path, default=KERDESEK)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="csak a kérdéseket és az elvárásokat írja ki (Ollama nélkül)")
    ap.add_argument("--json-out", action="store_true",
                    help="a nyers válaszokat is mentsd tool_reliability_raw_<dátum>.json-be")
    args = ap.parse_args()

    try:
        adat = json.loads(args.kerdesek.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"HIBA: nem tudom beolvasni a {args.kerdesek.name}-t: {e}", file=sys.stderr)
        return 1
    kerdesek = adat.get("kerdesek", [])
    if not kerdesek:
        print(f"HIBA: a {args.kerdesek.name} nem tartalmaz kérdéseket ('kerdesek').",
              file=sys.stderr)
        return 1

    if args.dry_run:
        for k in kerdesek:
            varas = (f"TILOS: {','.join(k['tilos'])}" if k["tipus"] == "negativ"
                     else " VAGY ".join(
                         v["name"] + (f" {v['args']}" if v.get("args") else "")
                         for v in k["varhato"]))
            print(f"{k['id']:6} [{k['tipus'][:3]}{'/mem' if k['memorizalt'] else ''}] "
                  f"{k['kerdes']}\n       -> {varas}")
        return 0

    if len(set(args.models)) != len(args.models):
        print(f"HIBA: ismétlődő modellnév: {args.models}", file=sys.stderr)
        return 1

    print(f"{len(args.models)} modell × {len(kerdesek)} kérdés × {args.repeat} ismétlés "
          f"= {len(args.models) * len(kerdesek) * args.repeat} generálás\n", file=sys.stderr)
    try:
        ki = futtat(args.models, kerdesek, args.repeat, args.timeout)
    except BenchmarkError as e:
        print(f"\nHIBA: {e}", file=sys.stderr)
        return 1

    print(file=sys.stderr)
    jelentes(args.models, kerdesek, ki, args.repeat)

    if args.json_out:
        p = HERE / f"tool_reliability_raw_{datetime.now().strftime('%Y-%m-%d')}.json"
        p.write_text(json.dumps(
            {"futtatva": datetime.now().isoformat(timespec="seconds"),
             "repeat": args.repeat, "seed_bazis": SEED_BAZIS,
             "modellek": args.models, "eredmenyek": ki},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nNyers adat → {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
