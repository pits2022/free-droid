#!/usr/bin/env python3
"""Anti-leakage guard: no dataset instruction may be a near-copy of an EVAL probe.

An eval set only measures *generalization* if the training data doesn't contain its
probes (verbatim or lightly reworded). This compares every freedroid_full.json
instruction against every probe in BOTH eval sets — red_team.json and
persona_benchmark.json — and fails if any pair is too close.

Both sets matter now that the HF chat Space is the primary eval loop: the red-team and
benchmark questions get typed into the chat, so mining the chat logs for new training
examples pastes eval probes straight into the dataset. That happened on 2026-07-24 — five
log-derived examples scored 0.82 (red-team) and 0.96 (persona) before rewording. Without
this guard the next round's "improvement" would be memorization.

    python _check_leakage.py            # report top matches per eval set + PASS/FAIL
    python _check_leakage.py --baseline # csak az ÚJ szivárgásra bukik (dataset-szerkesztés)
    python _check_leakage.py --record   # a jelenlegi ütközések rögzítése baseline-ként

Threshold 0.75: the 2026-07-07 v7 red-team patch peaked at 0.54 (same adversarial FRAME,
different wording). Topical overlap sits ~0.5; a near-verbatim paste scores >0.8.

KNOWN, NOT FIXED: 30 pre-existing dataset instructions match persona_benchmark probes at
>= 0.75 ("Állj meg!", "Szabi, gyere ide!", "Lány vagy fiú vagy?"). Those benchmark items
measure memorization today. A red_team ellen NULLA ilyen pár van.

A `--baseline` mód ezt a 30-at engedi át NÉV SZERINT (leakage_baseline.json), és minden
más küszöb fölötti párra bukik. A korábbi változat egy GLOBÁLIS 1.0-os limitet állított,
ami 2026-08-11-én bizonyítottan átengedett egy új 0.88-as szivárgást — a guard így a
saját céljával szemben működött.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "freedroid_full.json"
RED_TEAM = HERE.parent / "red_team.json"
PERSONA = HERE.parent / "persona_benchmark.json"
THRESHOLD = 0.75
# A korábbi, GLOBÁLIS baseline (PERSONA_BASELINE = 1.0) HASZNÁLHATATLAN volt, és ez mérve
# derült ki 2026-08-11-én: a limitet 1.0-ra állította, tehát a `--baseline` mód CSAK a
# szó szerinti átiratra bukott. Egy új, 0.88-as szivárgás ("Nézz fel, majd pásztázz
# körbe." vs a tc_05 próba "Nézz fel és pásztázz körbe.") némán átment rajta — pontosan
# az a fajta hiba, ami ellen a guard készült.
#
# Helyette PÁRONKÉNTI pillanatkép: a küszöb fölötti INSTRUCTION-ök rögzítve, és a
# `--baseline` mód arra bukik, ami NINCS a listában. A régi adósság így továbbra sem
# blokkol, egy új ütközés viszont igen — akkor is, ha 0.99.
BASELINE_FILE = HERE / "leakage_baseline.json"


def _probes(path: Path) -> list[str]:
    """Probe questions from an eval file (both use a `kerdesek` list of dicts)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["kerdesek"] if isinstance(raw, dict) else raw
    out = []
    for item in items:
        q = item.get("kerdes") if isinstance(item, dict) else item
        if q:
            out.append(str(q))
    return out


def _worst(instructions: list[str], probes: list[str]) -> list[tuple[float, str, str]]:
    scored = []
    for ins in instructions:
        ratio, probe = max(
            (difflib.SequenceMatcher(None, ins.lower(), p.lower()).ratio(), p) for p in probes
        )
        scored.append((ratio, ins, probe))
    scored.sort(reverse=True)
    return scored


def _baseline() -> dict[str, set[str]]:
    """A rögzített, ISMERT ütközések instruction-jei eval-készletenként."""
    if not BASELINE_FILE.exists():
        return {}
    raw = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    return {k: set(v) for k, v in raw.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8, help="how many closest pairs to print")
    ap.add_argument("--baseline", action="store_true",
                    help="csak az ISMERT (rögzített) ütközéseket engedd át; minden más "
                         "küszöb fölötti pár bukás — ezt akarják a dataset-szerkesztések")
    ap.add_argument("--record", action="store_true",
                    help="írd újra a leakage_baseline.json-t a MOSTANI állapotból. Csak "
                         "akkor futtasd, ha a fölötte lévő ütközéseket ÁTNÉZTED — ez a "
                         "flag elfogadja az adósságot, nem javítja.")
    args = ap.parse_args()
    baseline = _baseline()
    felvett: dict[str, list[str]] = {}

    full = json.loads(FULL.read_text(encoding="utf-8"))
    instructions = [ex.get("instruction", "") for ex in full if ex.get("instruction")]

    failed = False
    for label, path in (("red-team", RED_TEAM), ("persona", PERSONA)):
        worst = _worst(instructions, _probes(path))
        print(f"\n=== {label} ({path.name}) ===")
        for ratio, ins, probe in worst[: args.top]:
            print(f"  {ratio:.2f}  DS: {ins}\n        EV: {probe}")

        felette = [(r, i, p) for r, i, p in worst if r >= THRESHOLD]
        felvett[label] = sorted({i for _, i, _ in felette})
        ismert = baseline.get(label, set())
        ujak = [(r, i, p) for r, i, p in felette if i not in ismert]

        if args.baseline:
            ok = not ujak
            print(f"  küszöb fölött: {len(felette)} · ebből ismert: "
                  f"{len(felette) - len(ujak)} · ÚJ: {len(ujak)}  ->  "
                  f"{'PASS' if ok else 'FAIL — új szivárgás'}")
            for r, i, p in ujak[:args.top]:
                print(f"    ÚJ {r:.2f}  DS: {i}\n            EV: {p}")
        else:
            ok = not felette
            print(f"  max: {worst[0][0]:.2f}  (limit {THRESHOLD})  ->  "
                  f"{'PASS' if ok else 'FAIL — leakage'}")
        failed |= not ok

    if args.record:
        BASELINE_FILE.write_text(json.dumps(felvett, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        n = sum(len(v) for v in felvett.values())
        print(f"\nrögzítve: {BASELINE_FILE.name} ({n} ismert ütközés)")
        return 0

    print(f"\noverall: {'FAIL — leakage' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
