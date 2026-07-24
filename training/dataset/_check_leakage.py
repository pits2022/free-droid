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
    python _check_leakage.py --top 15   # show more

Threshold 0.75: the 2026-07-07 v7 red-team patch peaked at 0.54 (same adversarial FRAME,
different wording). Topical overlap sits ~0.5; a near-verbatim paste scores >0.8.

KNOWN, NOT FIXED: several pre-existing dataset examples match persona_benchmark probes at
1.00 ("Állj meg!", "Szabi, gyere ide!"). Those benchmark items measure memorization today.
Pass --baseline to fail only on NEW leakage (anything above the recorded baseline), which
is what CI/dataset edits want until the benchmark items are replaced.
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
# Pre-existing persona_benchmark overlap (2026-07-24). Raise nothing here: shrink it by
# fixing the dataset or swapping the benchmark item, then lower this number.
PERSONA_BASELINE = 1.0


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8, help="how many closest pairs to print")
    ap.add_argument("--baseline", action="store_true",
                    help="fail only on leakage ABOVE the recorded pre-existing baseline")
    args = ap.parse_args()

    full = json.loads(FULL.read_text(encoding="utf-8"))
    instructions = [ex.get("instruction", "") for ex in full if ex.get("instruction")]

    failed = False
    for label, path, baseline in (("red-team", RED_TEAM, THRESHOLD),
                                  ("persona", PERSONA,
                                   PERSONA_BASELINE if args.baseline else THRESHOLD)):
        worst = _worst(instructions, _probes(path))
        print(f"\n=== {label} ({path.name}) ===")
        for ratio, ins, probe in worst[: args.top]:
            print(f"  {ratio:.2f}  DS: {ins}\n        EV: {probe}")
        top = worst[0][0]
        ok = top <= baseline if baseline >= 1.0 else top < baseline
        failed |= not ok
        print(f"  max: {top:.2f}  (limit {baseline})  ->  {'PASS' if ok else 'FAIL — leakage'}")

    print(f"\noverall: {'FAIL — leakage' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
