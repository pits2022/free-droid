#!/usr/bin/env python3
"""Anti-leakage guard: no dataset instruction may be a near-copy of a red-team probe.

The red-team benchmark (red_team.json) only measures *generalization* if the training
data doesn't contain the probes themselves (verbatim or lightly reworded). This script
compares every freedroid_full.json instruction against every red_team.json probe with a
difflib similarity ratio and fails if any pair is too close — so a future dataset edit
that accidentally pastes a probe is caught before it silently invalidates the benchmark.

    python _check_leakage.py            # report top matches + PASS/FAIL
    python _check_leakage.py --top 15   # show more

Threshold 0.75: the 2026-07-07 v7 red-team patch peaked at 0.54 (same adversarial FRAME,
different wording). Topical overlap sits ~0.5; a near-verbatim paste scores >0.8.
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
THRESHOLD = 0.75


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8, help="how many closest pairs to print")
    args = ap.parse_args()

    full = json.loads(FULL.read_text(encoding="utf-8"))
    probes = [q["kerdes"] for q in json.loads(RED_TEAM.read_text(encoding="utf-8"))["kerdesek"]]

    worst = []
    for ex in full:
        ins = ex.get("instruction", "")
        if not ins:
            continue
        ratio, probe = max(
            (difflib.SequenceMatcher(None, ins.lower(), p.lower()).ratio(), p) for p in probes
        )
        worst.append((ratio, ins, probe))
    worst.sort(reverse=True)

    for ratio, ins, probe in worst[: args.top]:
        print(f"  {ratio:.2f}  EXT: {ins}\n        RT : {probe}")

    top = worst[0][0]
    ok = top < THRESHOLD
    print(f"\nmax similarity: {top:.2f}  (threshold {THRESHOLD})  ->  {'PASS' if ok else 'FAIL — leakage'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
