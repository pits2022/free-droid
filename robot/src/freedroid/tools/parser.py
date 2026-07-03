"""Parser for the LLM tool-calling grammar.

Positional grammar (v5+): ``<tool>NAME v1 v2 ...</tool>`` — space-separated, no
parentheses or quotes. Small models emit this far more reliably than the earlier
``fn(key="value")`` form, and Python parses it trivially. Parsing is
unambiguous because the argument value-domains are disjoint: a number is a
distance/degrees, a word is a direction / speed / mode / action (looked up in the
enums), and ``until`` is a literal marker. Examples from the dataset::

    <tool>move forward 2</tool>            -> distance=2.0
    <tool>move forward slow</tool>         -> speed=slow
    <tool>move forward until obstacle</tool>
    <tool>move approach_speaker</tool>     -> mode only (no direction)
    <tool>turn left 90</tool>              -> degrees=90 (int)
    <tool>camera pan left 45</tool>
    <tool>set_mode standby</tool>
    <tool>request_navigation_help piros szék</tool>   # rest-of-line = target
    <tool>set_oracle off</tool>            -> enabled=False
    <tool>stop</tool>

request_navigation_help is the only free-text tool: everything after the name is
the target (so it may contain spaces). Multiple calls per response are allowed;
prose outside <tool> blocks is ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..camera import CameraAction
from ..motion.types import Direction, Mode, Speed, TurnDir

_BLOCK = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)
_DIRECTIONS = {d.value for d in Direction} | {d.value for d in TurnDir}
_SPEEDS = {s.value for s in Speed}
_MODES = {m.value for m in Mode}
_CAMERA_ACTIONS = {c.value for c in CameraAction}


@dataclass(frozen=True)
class ParsedTool:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


def parse_tools(text: str) -> list[ParsedTool]:
    """Extract every <tool>...</tool> call from an LLM response, in order."""
    return [_parse_one(m.group(1)) for m in _BLOCK.finditer(text or "")]


def _is_num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _parse_one(inner: str) -> ParsedTool:
    toks = inner.split()
    if not toks:
        raise ValueError(f"empty tool call: {inner!r}")
    name, rest = toks[0], toks[1:]
    args: dict[str, Any] = {}

    if name == "stop":
        pass
    elif name == "scan_wifi":
        if rest:  # optional filter/sort sub-keyword, e.g. "scan_wifi filter wpa3"
            args[rest[0]] = rest[1]
    elif name == "set_speed":
        args["level"] = rest[0]
    elif name == "set_mode":
        args["mode"] = rest[0]
    elif name == "set_oracle":
        args["enabled"] = rest[0] == "on"
    elif name == "request_navigation_help":
        args["target"] = " ".join(rest)  # free text — the whole remainder
    elif name == "camera":
        if rest and rest[0] in ("pan", "tilt"):
            args[rest[0]] = rest[1]
            args["degrees"] = int(rest[2])
        elif rest:
            args["action"] = rest[0]
    elif name in ("move", "turn"):
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok == "until":
                args["until"] = rest[i + 1]
                i += 2
                continue
            if tok in _DIRECTIONS:
                args["direction"] = tok
            elif tok in _SPEEDS:
                args["speed"] = tok
            elif tok in _MODES:
                args["mode"] = tok
            elif _is_num(tok):
                args["degrees" if name == "turn" else "distance"] = (
                    int(float(tok)) if name == "turn" else float(tok))
            i += 1

    return ParsedTool(name, args)
