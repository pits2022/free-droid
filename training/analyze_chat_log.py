#!/usr/bin/env python3
"""Mérőszalag a HF chat-logokra — a Space-en folyó csevegés a fő eval-hurok.

    hf download jabba77/szabi-chat-logs --repo-type dataset --local-dir szabi-logs
    python analyze_chat_log.py szabi-logs/data/*.jsonl
    python analyze_chat_log.py --before régi.jsonl --after új.jsonl    # két kör összevetése

Amit mér (mind a 2026-07-23-i kézi elemzésből, ami kétszer is újraíródott):

- **panel-arány**: hány válaszban van mantra / RAG-meta / konzerv-mondat. Ez a
  „robotos, szögletes" érzés egyetlen számmá sűrítve. Baseline-ok: régi prompt 39%,
  anti-stiffness prompt 27%.
- **tool-hívások**: darabszám + kitalált tool-nevek (a `freedroid.tools.parser`
  KNOWN_TOOLS-a alapján, nem külön listából).
- **válaszhossz**: a persona_voice.md szerint 1–3 rövid mondat az alap; a hosszú
  válasz hallucináció-szag.
- **eval-ütközés**: mely elhangzott kérdések esnek egybe a red_team.json /
  persona_benchmark.json próbáival. EZEKET NE MÁSOLD A DATASETBE — a chat-hurokban a
  benchmark-kérdéseket is begépeljük, így a logból bányászott tanminta pont az
  eval-készletet tanítaná be. (A `dataset/_check_leakage.py` a másik védvonal.)

A minták heurisztikák, nem igazság: ha egy kategória rendre félrelő, itt kell javítani.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot" / "src"))
from freedroid.tools.parser import KNOWN_TOOLS, parse_tools  # noqa: E402

# Egy válasz "panel", ha ezek bármelyike illeszkedik rá.
PATTERNS: dict[str, str] = {
    # a fine-tune-olt mantra-reflex: értékrend felmondása oda nem illő kérdésre
    "mantra_dualizmus": r"dualizmus",
    "mantra_erenyek": r"(három erény|Szeretet, Bölcsesség|három nádszál)",
    # sosem szabadna kimondania, hogy forrásból dolgozik (a RAG-fix ezt célozza)
    "rag_meta": r"(a választ? a forrásban|forrásban (van|nincs|találtam)|nem találtam a válasz)",
    # a v7-ben megfigyelt értelmetlen konzerv-mondat, gyakran E/2-ben
    "konzerv_halozat": r"nem vagyok hozzá kötve, a hálózatra",
}
PANEL_KEYS = tuple(PATTERNS)

EVAL_FILES = {"red-team": HERE / "red_team.json",
              "persona": HERE / "persona_benchmark.json"}
EVAL_HIT = 0.75   # ugyanaz a küszöb, mint a dataset-oldali szivárgás-őrben


def load_turns(paths: list[Path]) -> list[dict]:
    turns = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                turns.append(json.loads(line))
    return turns


def eval_probes() -> list[tuple[str, str]]:
    out = []
    for label, path in EVAL_FILES.items():
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw["kerdesek"] if isinstance(raw, dict) else raw
        for item in items:
            q = item.get("kerdes") if isinstance(item, dict) else item
            if q:
                out.append((label, str(q)))
    return out


def measure(turns: list[dict]) -> dict:
    n = len(turns) or 1
    counts = {k: sum(bool(re.search(p, t["assistant"], re.I | re.M)) for t in turns)
              for k, p in PATTERNS.items()}
    panel = sum(1 for t in turns
                if any(re.search(PATTERNS[k], t["assistant"], re.I | re.M) for k in PANEL_KEYS))
    names = [c.name for t in turns for c in parse_tools(t["assistant"])]
    unknown = [x for x in names if x not in KNOWN_TOOLS]
    with_tool = sum(1 for t in turns if "<tool>" in t["assistant"])
    lengths = sorted(len(re.findall(r"[.!?]+", t["assistant"])) or 1 for t in turns)
    return {"n": len(turns), "counts": counts, "panel": panel, "panel_pct": 100 * panel / n,
            "tools": len(names), "unknown": unknown, "with_tool": with_tool,
            "median_sentences": lengths[len(lengths) // 2] if lengths else 0,
            "long_replies": sum(1 for x in lengths if x > 4)}


def report(label: str, m: dict) -> None:
    n = m["n"] or 1
    print(f"\n=== {label}  (n={m['n']} váltás)")
    print(f"  PANEL-ARÁNY            {m['panel']:4} / {m['n']}  = {m['panel_pct']:.0f}%")
    for k, c in m["counts"].items():
        print(f"    {k:22} {c:4}  {100 * c / n:5.1f}%")
    print(f"  tool-hívás             {m['tools']:4}  ({m['with_tool']} válaszban)")
    bad = Counter(m["unknown"])
    print(f"  KITALÁLT tool-név      {len(m['unknown']):4}"
          + (f"  {dict(bad)}" if bad else "  ✅"))
    print(f"  medián mondatszám      {m['median_sentences']:4}"
          f"   (>4 mondat: {m['long_replies']} válasz)")


def report_eval_collisions(turns: list[dict], top: int) -> None:
    probes = eval_probes()
    if not probes:
        print("\n(eval-fájlok nem találhatók — ütközés-ellenőrzés kihagyva)")
        return
    asked = sorted({t["user"].strip() for t in turns})
    hits = []
    for q in asked:
        ratio, (label, probe) = max(
            (difflib.SequenceMatcher(None, q.lower(), p.lower()).ratio(), (lab, p))
            for lab, p in probes)
        if ratio >= EVAL_HIT:
            hits.append((ratio, label, q, probe))
    hits.sort(reverse=True)
    print(f"\n=== EVAL-ÜTKÖZÉS  ({len(hits)} elhangzott kérdés ≥ {EVAL_HIT})")
    print("  Ezeket NE másold tanmintának — az eval-készletet tanítanád be.")
    for ratio, label, q, probe in hits[:top]:
        print(f"  {ratio:.2f} [{label}] {q[:66]}")
        if ratio < 1.0:
            print(f"        ~ {probe[:66]}")
    if len(hits) > top:
        print(f"  … és még {len(hits) - top} (lásd --top)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*", type=Path, help="chat-log .jsonl fájl(ok)")
    ap.add_argument("--before", nargs="+", type=Path, help="összevetés: korábbi kör")
    ap.add_argument("--after", nargs="+", type=Path, help="összevetés: későbbi kör")
    ap.add_argument("--top", type=int, default=12, help="hány eval-ütközést listázzon")
    args = ap.parse_args()

    if args.before and args.after:
        b, a = measure(load_turns(args.before)), measure(load_turns(args.after))
        report("ELŐTTE", b)
        report("UTÁNA", a)
        delta = a["panel_pct"] - b["panel_pct"]
        print(f"\n  panel-arány változás: {b['panel_pct']:.0f}% -> {a['panel_pct']:.0f}% "
              f"({delta:+.0f} pont)")
        report_eval_collisions(load_turns(args.after), args.top)
        return 0

    if not args.logs:
        ap.error("adj meg log-fájlokat, vagy --before/--after párost")
    turns = load_turns(args.logs)
    report("CHAT-LOG", measure(turns))
    report_eval_collisions(turns, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
