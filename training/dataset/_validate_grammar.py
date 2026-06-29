#!/usr/bin/env python3
"""Standalone mirror of robot/tests/test_grammar.py + conftest parsing.

pytest can't build lgpio off-Pi, so this reproduces the grammar contract directly
over the combined dataset (freedroid_full.json + tool_calls_expansion.json) to
prove the expansion keeps the reverse contract intact.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "robot" / "src"))

# Import the real grammar enums (no hardware deps → they load off-Pi, as test_grammar.py
# does) so a new enum value can't slip past this validator the way a hardcoded mirror would.
from freedroid.camera import CameraAction  # noqa: E402
from freedroid.motion.types import Direction, Mode, Speed, TurnDir  # noqa: E402

# Tool names have no code enum (they are a spec list); mirrors robot/tests/test_grammar.py.
KNOWN_TOOLS = {
    "move", "turn", "stop", "camera",
    "set_speed", "set_mode", "request_navigation_help", "scan_wifi", "set_oracle",
}
ENUMS = {
    "Direction": {m.value for m in Direction},
    "TurnDir": {m.value for m in TurnDir},
    "Speed": {m.value for m in Speed},
    "Mode": {m.value for m in Mode},
    "CameraAction": {m.value for m in CameraAction},
}

_TOOL_RE = re.compile(r"<tool>(.*?)</tool>", re.S)
_CALL_RE = re.compile(r"^\s*([a-z_]+)\s*\((.*)\)\s*$", re.S)


def _parse_arg(arg: str):
    arg = arg.strip()
    if "=" in arg:
        k, v = arg.split("=", 1)
        return k.strip(), v.strip().strip('"')
    return None, arg.strip().strip('"')


def load_tool_calls(paths: list[Path]) -> list[dict]:
    calls = []
    for p in paths:
        for ex in json.loads(p.read_text(encoding="utf-8")):
            for raw in _TOOL_RE.findall(ex.get("output", "")):
                m = _CALL_RE.match(raw.strip())
                if not m:
                    continue
                name, inside = m.group(1), m.group(2).strip()
                args, positional = {}, []
                if inside:
                    for part in inside.split(","):
                        key, val = _parse_arg(part)
                        (positional.append(val) if key is None else args.__setitem__(key, val))
                calls.append({"name": name, "args": args, "positional": positional})
    return calls


def _dataset_modes(tc) -> set[str]:
    modes = set()
    for c in tc:
        if c["name"] in ("move", "turn") and "mode" in c["args"]:
            modes.add(c["args"]["mode"])
        if c["name"] == "set_mode":
            modes.update(c["positional"])
            if "mode" in c["args"]:
                modes.add(c["args"]["mode"])
    return modes


def main() -> int:
    paths = [HERE / "freedroid_full.json", HERE / "tool_calls_expansion.json"]
    tc = load_tool_calls(paths)
    checks: list[tuple[str, bool, str]] = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    seen = {c["name"] for c in tc}
    chk("every dataset tool is known", seen <= KNOWN_TOOLS, f"unknown={seen - KNOWN_TOOLS}")

    move_dirs = {c["args"]["direction"] for c in tc if c["name"] == "move" and "direction" in c["args"]}
    chk("move directions == Direction (reverse)", move_dirs == ENUMS["Direction"], f"{move_dirs}")

    turn_dirs = {c["args"]["direction"] for c in tc if c["name"] == "turn" and "direction" in c["args"]}
    chk("turn directions == TurnDir (reverse)", turn_dirs == ENUMS["TurnDir"], f"{turn_dirs}")

    speeds = {c["args"]["speed"] for c in tc if c["name"] == "move" and "speed" in c["args"]}
    speeds |= {c["args"]["level"] for c in tc if c["name"] == "set_speed" and "level" in c["args"]}
    chk("speeds subset of Speed", speeds <= ENUMS["Speed"], f"{speeds}")

    modes = _dataset_modes(tc)
    chk("modes == Mode (reverse, incl positional)", modes == ENUMS["Mode"], f"{modes}")

    actions = {c["args"]["action"] for c in tc if c["name"] == "camera" and "action" in c["args"]}
    chk("camera actions == CameraAction (reverse)", actions == ENUMS["CameraAction"], f"{actions}")

    oracle = {c["args"]["enabled"] for c in tc if c["name"] == "set_oracle" and "enabled" in c["args"]}
    chk("set_oracle enabled in {true,false}", oracle and oracle <= {"true", "false"}, f"{oracle}")

    chk("positional args exist somewhere", any(c["positional"] for c in tc))

    sm_pos = {v for c in tc if c["name"] == "set_mode" for v in c["positional"]}
    chk("set_mode positional values are valid modes", sm_pos <= ENUMS["Mode"], f"{sm_pos}")

    # also: any until= values stay 'obstacle' (StopCond)
    untils = {c["args"]["until"] for c in tc if "until" in c["args"]}
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
