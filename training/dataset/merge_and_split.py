#!/usr/bin/env python3
"""Merge staged additions into freedroid_full.json and regenerate the train/val split.

Run this ONCE, after the dataset additions (tool expansion + any persona rewrites)
are approved — not per-edit. It is deterministic (seeded shuffle) so the split is
reproducible. The grammar contract (robot/tests) reads freedroid_full.json directly,
so it is unaffected by the split; train/val are only for the fine-tune loop.

Usage:
    python merge_and_split.py            # dry-run: report what would change
    python merge_and_split.py --write    # merge + rewrite full/train/val

Staging files merged (if present): tool_calls_expansion.json
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "freedroid_full.json"
STAGING = [HERE / "tool_calls_expansion.json", HERE / "rag_category.json"]
TRAIN = HERE / "train.jsonl"
VAL = HERE / "val.jsonl"

SEED = 42
VAL_RATIO = 0.10


def _key(ex: dict) -> tuple[str, str]:
    return (ex.get("instruction", ""), ex.get("output", ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="actually write files (default: dry-run)")
    args = ap.parse_args()

    full = json.loads(FULL.read_text(encoding="utf-8"))
    seen = {_key(e) for e in full}

    added = 0
    for sp in STAGING:
        if not sp.exists():
            continue
        for ex in json.loads(sp.read_text(encoding="utf-8")):
            if _key(ex) not in seen:
                full.append({"instruction": ex.get("instruction", ""),
                             "input": ex.get("input", ""),
                             "output": ex.get("output", "")})
                seen.add(_key(ex))
                added += 1

    rng = random.Random(SEED)
    shuffled = full[:]
    rng.shuffle(shuffled)
    n_val = round(len(shuffled) * VAL_RATIO)
    val, train = shuffled[:n_val], shuffled[n_val:]

    print(f"merged additions:   +{added}")
    print(f"total examples:     {len(full)}")
    print(f"train / val split:  {len(train)} / {len(val)}  (seed={SEED}, val_ratio={VAL_RATIO})")

    if not args.write:
        print("\ndry-run; re-run with --write to apply.")
        return 0

    FULL.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with TRAIN.open("w", encoding="utf-8") as f:
        for ex in train:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    with VAL.open("w", encoding="utf-8") as f:
        for ex in val:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print("\nwrote freedroid_full.json, train.jsonl, val.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
