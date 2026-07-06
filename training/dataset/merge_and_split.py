#!/usr/bin/env python3
"""Merge staged additions into freedroid_full.json and regenerate the train/val split.

Run this ONCE, after the dataset additions (tool expansion + any persona rewrites)
are approved — not per-edit. It is deterministic (seeded shuffle) so the split is
reproducible. The grammar contract (robot/tests) reads freedroid_full.json directly,
so it is unaffected by the split; train/val are only for the fine-tune loop.

Usage:
    python merge_and_split.py            # dry-run: report what would change
    python merge_and_split.py --write    # merge + rewrite full/train/val

Staging lifecycle: a staging file lives at one of the STAGING paths (below) WHILE it
is being built/reviewed. Once merged into freedroid_full.json and committed, archive it
to dataset/old/ — merge skips missing staging files, and its content already lives in
full. To add a new batch: drop a file at a STAGING path, run --write, then archive it.
(The current staging slots are all archived; a fresh run is a no-op +0.)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / "freedroid_full.json"
STAGING = [HERE / "tool_calls_expansion.json", HERE / "rag_category.json",
           HERE / "freedroid-ext.json"]
TRAIN = HERE / "train.jsonl"
VAL = HERE / "val.jsonl"

SEED = 42
VAL_RATIO = 0.10

# Entries removed from the merged dataset. Matched on exact instruction text.
#  - Bare-fact answers that conflict with the RAG corpus (facts belong in RAG).
#  - Whimsy folklore prompts (népmese / táltos / sárkány …): demo-irrelevant and the
#    question itself baits metaphor-heavy answers a small model can't learn cleanly
#    (dropped in the 2026-06-30 simple-language pass, not rewritten).
DROP = {
    "Ki volt Máté Imre?",
    "Hogyan hasonlítanád össze a Raspberry Pi 5-öt a népmesei Táltos Paripával?",
    "Hogyan látod a 'Hétfejű Sárkányt' a modern digitális világban?",
    "Hogyan értelmezed a 'táltos viaskodást' a kiber-védekezésben?",
    "Ki vagy te a magyar népmesék nyelvén?",
    "Mit jelent a 'Hétfejű Sárkány' modern megfelelője?",
    "Mit jelent a 'Táltos-paripa' analógia a technológiában?",
    "Mit jelent a 'csodaszarvas' követése a kutatás-fejlesztésben?",
    "Mit jelent számodra a 'Népmesei Igazság'?",
    "Mit jelent számodra a 'csodaszarvas' iránytűje a bizonytalan adatok között?",
    "Mit jelent számodra a 'népmesei igazság'?",
    # 2026-07-06 tény→RAG pass: tiszta Yotengrit-lore lookup-ok → rag/_staged_from_dataset.md
    # (a persona-ba csomagolt tény hallucinációt tanít; a tényt a RAG szállítja).
    "Kérdés: 'Ki az a 'Yotengrit' valójában?'",
    "Mi az a Yotengrit?",
    "Mit jelent a duál-egység a Yotengritben?",
    "Mit mond a Yotengrit a szeretetről?",
    "A Yotengrit vallás?",
}


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

    dropped = sum(1 for e in full if e.get("instruction") in DROP)
    full = [e for e in full if e.get("instruction") not in DROP]

    rng = random.Random(SEED)
    shuffled = full[:]
    rng.shuffle(shuffled)
    n_val = round(len(shuffled) * VAL_RATIO)
    val, train = shuffled[:n_val], shuffled[n_val:]

    print(f"merged additions:   +{added}")
    print(f"dropped (DROP set):  -{dropped}")
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
