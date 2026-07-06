#!/usr/bin/env python3
"""Standalone mirror of robot/tests/test_grammar.py, runnable off-Pi.

pytest can't build lgpio off-Pi, so this reproduces the grammar contract directly
over freedroid_full.json (the single source of truth — staging files are merged
into it) using the SAME parser the tests use (freedroid.tools.parser.parse_tools)
— no hardcoded parsing or enum mirrors, so nothing can drift past it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "robot" / "src"))

# Real parser + enums (pure-python, load off-Pi like test_grammar.py).
from freedroid.camera import CameraAction  # noqa: E402
from freedroid.motion.types import Direction, Mode, Speed, TurnDir  # noqa: E402
from freedroid.tools.parser import ToolParseError, parse_tools  # noqa: E402

KNOWN_TOOLS = {
    "move", "turn", "stop", "camera",
    "set_speed", "set_mode", "request_navigation_help", "scan_wifi", "set_oracle",
}


def _vals(enum) -> set[str]:
    return {m.value for m in enum}


def load_tool_calls(paths: list[Path]):
    calls = []
    for p in paths:
        for ex in json.loads(p.read_text(encoding="utf-8")):
            # strict: unknown token / missing arg raises (naming the call) rather
            # than being silently dropped before the enum checks can see it.
            calls.extend(parse_tools(ex.get("output", ""), strict=True))
    return calls


def main() -> int:
    paths = [HERE / "freedroid_full.json"]
    try:
        tc = load_tool_calls(paths)
    except ToolParseError as e:
        print(f"  [FAIL] a dataset egy tool-hívása nem parse-olható: {e}")
        print("\nCONTRACT BROKEN")
        return 1
    checks: list[tuple[str, bool, str]] = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    def collect(name, key):
        return {c.args[key] for c in tc if c.name == name and key in c.args}

    seen = {c.name for c in tc}
    chk("every dataset tool is known", seen <= KNOWN_TOOLS, f"unknown={seen - KNOWN_TOOLS}")
    chk("move directions == Direction", collect("move", "direction") == _vals(Direction),
        f"{collect('move', 'direction')}")
    chk("turn directions == TurnDir", collect("turn", "direction") == _vals(TurnDir),
        f"{collect('turn', 'direction')}")

    speeds = collect("move", "speed") | collect("set_speed", "level")
    chk("speeds subset of Speed", speeds <= _vals(Speed), f"{speeds - _vals(Speed)}")

    modes = {c.args["mode"] for c in tc if "mode" in c.args}
    chk("modes == Mode", modes == _vals(Mode), f"{modes}")
    chk("camera actions == CameraAction", collect("camera", "action") == _vals(CameraAction),
        f"{collect('camera', 'action')}")

    pans, tilts = collect("camera", "pan"), collect("camera", "tilt")
    chk("camera pan/tilt directions valid",
        pans <= {"left", "right"} and tilts <= {"up", "down"}, f"pan={pans} tilt={tilts}")

    oracle = collect("set_oracle", "enabled")
    chk("set_oracle enabled is {True,False}", oracle == {True, False}, f"{oracle}")

    untils = {c.args["until"] for c in tc if "until" in c.args}
    chk("until values subset of {obstacle}", untils <= {"obstacle"}, f"{untils}")

    print(f"parsed {len(tc)} tool calls across {len(paths)} files\n")
    ok = True
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if not passed else ""))
        ok &= passed
    print("\n" + ("ALL GREEN" if ok else "CONTRACT BROKEN"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
