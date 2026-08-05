#!/usr/bin/env python3
"""Epoch-jelöltek összevetése a v11 HÁROM CÉLJÁN — mechanikusan, judge nélkül.

MIÉRT NEM A LOSS DÖNT: az `eval_loss` VÉTÓ, nem választás. Ha egy epochnál emelkedik,
az az epoch kiesik (túltanulás). Ha végig ereszkedik, akkor egyik sem esik ki, és a
loss nem mond többet — a repó régi tanulsága szerint az alacsony loss nem persona-
minőség („Don't chase low loss", CLAUDE.md).

MIÉRT NEM (CSAK) A VAK ARÉNA DÖNT: n=25-nél a bináris arány CI-je 45–83%. Arra jó,
hogy „vállalható-e a demóra", arra nem, hogy „epoch 2 vagy 3". Két szomszédos epoch
különbsége pont abba a sávba esik, amit a minta nem bír el.

AMI VISZONT ÉLES: a v11 három célja nem arány-becslés, hanem MECHANIZMUS-kérdés.
„Megjelent-e egyáltalán a hosszú válasz" nem statisztika — ha a koherencia-kérdésekre
továbbra is 30 szavas válasz jön, az a checkpoint nem tanulta meg az új adatot,
akármit mond a loss. Ez a három:

  1. HOSSZ a koherencia-dimenzión — a 18 új példa 100–106 szavas. Ha a válasz nem
     nyúlik meg, a checkpoint nem látta eleget őket.
  2. KÖSZÖNÉS-VISZONZÁS — a v10 non sequiturt adott („Jó reggelt" -> „Reggeli árnyék.").
     A viszonzás-szólistát a dataset-építőből importáljuk, hogy ne csússzon szét.
  3. MEGSZÓLÍTÁS-ARÁNY — a dataset 50%; a v8 chat-logban 12% jött ki. Mennyi jön most?

Plusz a két ismert romlás-jel, hogy a javítás ne kerüljön másba: KITALÁLT tool-név és
CSUPASZ tool-hívás (kísérő mondat nélkül) — a v8 fő hibája.

    python run_benchmark.py --models szabi-3b-e1 szabi-3b-e2 szabi-3b-e3 --json-out
    python compare_epochs.py benchmark_raw_<dátum>.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot" / "src"))
sys.path.insert(0, str(HERE / "dataset"))

from freedroid.tools.parser import KNOWN_TOOLS, parse_tools  # noqa: E402

# A viszonzás-szólista a dataset-építő EGYETLEN forrásából jön: ha ott bővül, itt is.
from _build_greetings import KOSZONES_JELEK  # noqa: E402

MEGSZOLITAS = re.compile(r"(,\s*Teremtőm[!?.…:;]|(?<![\wáéíóöőúüű])Teremtőm[,!:;]\s)")
# Köszönés-próba: a kérdés köszönést KÉR (nem a válasz dönti el, hogy annak kellett-e lennie).
KOSZONES_PROBA = re.compile(r"(köszönj|üdvözöl|búcsúz|jó reggelt|jó napot|jó estét|szia)", re.I)
TOOL_BLOKK = re.compile(r"<tool>.*?</tool>", re.S)
# Tool-SZÁNDÉK: a modell nyilván hívni akart, de a szintaxis megcsonkult. A v11 3B-ben
# ilyen volt a `*tool>camera tilt up 30</tool>` (csillag a `<` helyett) és a
# `(camera tilt up 30)` zárójeles ál-tool. Ezek a parsernek NEM léteznek, tehát a
# "kitalált tool-név" számláló sem látja őket — csendben elvesznek. Fallbacknél ez a
# legrosszabb fajta hiba: a mozgásparancs nem hajtódik végre, és nyoma sincs.
TOOL_SZANDEK = re.compile(r"(?:[*<]\s*tool\s*>|\(\s*(?:move|turn|stop|camera|set_speed|"
                          r"set_mode|scan_wifi|set_oracle)\b[^)]*\))", re.I)


def cellak(raw: dict, label: str) -> list[tuple[dict, str]]:
    """(kérdés, válasz) párok egy oszlopra; a kihagyott (TIMEOUT) cellák nélkül."""
    out = []
    for e in raw["eredmenyek"]:
        c = (e.get("valaszok") or {}).get(label)
        if c and not c.get("skipped"):
            out.append((e, c["valasz"]))
    return out


def meres(parok: list[tuple[dict, str]]) -> dict:
    koherencia = [v for e, v in parok if e["dimenzio"] == "koherencia"]
    koszones = [v for e, v in parok if KOSZONES_PROBA.search(e["kerdes"])]
    toolos = [v for e, v in parok if "<tool>" in v]
    kitalalt = [c.name for _, v in parok for c in _safe_parse(v) if c.name not in KNOWN_TOOLS]
    # Csupasz tool-hívás: a válaszban a tool-blokkon kívül nincs érdemi mondat.
    csupasz = sum(1 for v in toolos if len(TOOL_BLOKK.sub("", v).split()) < 3)
    # Elveszett blokk: annyival több tool-SZÁNDÉK van a szövegben, mint ahány ép
    # <tool>...</tool> blokk. A különbség az, ami a parserig el sem jut.
    elveszett = sum(max(0, len(TOOL_SZANDEK.findall(v)) - len(TOOL_BLOKK.findall(v)))
                    for _, v in parok)
    hosszak = [len(v.split()) for v in koherencia]
    return {
        "n": len(parok),
        "koherencia_atlag": sum(hosszak) / len(hosszak) if hosszak else 0,
        "koherencia_max": max(hosszak) if hosszak else 0,
        "koszones_n": len(koszones),
        "koszones_ok": sum(1 for v in koszones
                           if any(j in v.lower() for j in KOSZONES_JELEK)),
        "megszolitas": sum(1 for _, v in parok if MEGSZOLITAS.search(v)),
        "kitalalt_tool": len(kitalalt),
        "kitalalt_nevek": sorted(set(kitalalt)),
        "csupasz_tool": csupasz,
        "elveszett_tool": elveszett,
        "toolos": len(toolos),
    }


def _safe_parse(valasz: str):
    try:
        return parse_tools(valasz)
    except Exception:      # noqa: BLE001 — hibás grammatika: a kitalált nevet így is akarjuk látni
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", type=Path, help="a run_benchmark.py --json-out kimenete")
    args = ap.parse_args()
    try:
        raw = json.loads(args.raw.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"HIBA: {e}", file=sys.stderr)
        return 1

    labels = [o["label"] for o in raw["meta"]["oszlopok"]]
    m = {lab: meres(cellak(raw, lab)) for lab in labels}

    print(f"# Epoch-összevetés — {args.raw.name}\n")
    print("| Mérőszám | " + " | ".join(labels) + " |")
    print("| :--- |" + " ---: |" * len(labels))

    def sor(cim, kulcs, fmt="{:.0f}"):
        print(f"| {cim} | " + " | ".join(fmt.format(m[lab][kulcs]) for lab in labels) + " |")

    sor("koherencia-válasz átlaghossz (szó)", "koherencia_atlag", "{:.0f}")
    sor("koherencia-válasz leghosszabb", "koherencia_max")
    print("| köszönést viszonoz | " + " | ".join(
        f"{m[lab]['koszones_ok']}/{m[lab]['koszones_n']}" for lab in labels) + " |")
    print("| megszólítás ('Teremtőm') | " + " | ".join(
        f"{m[lab]['megszolitas']}/{m[lab]['n']} = {100 * m[lab]['megszolitas'] / m[lab]['n']:.0f}%"
        if m[lab]["n"] else "—" for lab in labels) + " |")
    sor("KITALÁLT tool-név ⬇", "kitalalt_tool")
    sor("ELVESZETT tool-blokk ⬇", "elveszett_tool")
    print("| csupasz tool-hívás ⬇ | " + " | ".join(
        f"{m[lab]['csupasz_tool']}/{m[lab]['toolos']}" for lab in labels) + " |")

    print("\n## Olvasat\n")
    print("- A **koherencia-hossz** a v11 tétje: a 18 új példa 100–106 szavas. Ha egy")
    print("  oszlop itt a v10 szintjén marad, az a checkpoint nem tanulta meg az új adatot —")
    print("  és akkor NEM az epoch-szám a hibás, hanem az adat nem jutott el hozzá.")
    print("- A **kitalált tool-név** és a **csupasz tool-hívás** a romlás-őrök: ha ezek nőnek,")
    print("  a hosszabb tanítás mást rontott el. Ilyenkor a kisebb epoch-szám nyer.")
    print("- Ez a tábla a MECHANIZMUST méri, nem a minőséget. A 'vállalható-e a demóra'")
    print("  kérdésre a vak, bináris aréna válaszol (run_benchmark.py --anchor + --decode).")
    for lab in labels:
        if m[lab]["kitalalt_nevek"]:
            print(f"\n  ⚠ {lab}: kitalált tool-nevek: {', '.join(m[lab]['kitalalt_nevek'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
