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

**Robustness contract — this is a trust boundary.** Callers feed it raw output
from a small, unreliable model (truncated generation, typos, wrong grammar).
Two modes:

- **Tolerant (default, runtime):** a malformed block is *dropped*, not crashed on;
  valid sibling blocks in the same response still parse. Fail-closed — an
  un-mappable motion call becomes no call at all, never a wrong motor command.
- **Strict (``strict=True``, dataset validator + contract tests):** a malformed
  block raises ``ToolParseError`` naming the offending call, so bad training data
  can't drift past the guard by being silently normalized away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..motion.types import Direction, Mode, Speed, TurnDir

# The names this parser can actually dispatch (see `_parse_one`). Exported for callers
# that must judge whether a model invented a tool name — the parser itself is tolerant and
# keeps an unknown name so the caller can see what was attempted. `tests/test_grammar.py`
# keeps its OWN literal copy on purpose: that one mirrors the spec, so the pair catches
# code-vs-spec drift. Don't collapse them into one.
KNOWN_TOOLS = frozenset({
    "move", "turn", "stop", "camera",
    "set_speed", "set_mode", "request_navigation_help", "scan_wifi",
    "set_oracle",
})

_BLOCK = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)
_MOVE_DIRS = {d.value for d in Direction}
_TURN_DIRS = {d.value for d in TurnDir}
_SPEEDS = {s.value for s in Speed}
_MODES = {m.value for m in Mode}
_WIFI_KEYS = {"filter", "sort"}
_PAN = {"left", "right"}
_TILT = {"up", "down"}


class ToolParseError(ValueError):
    """A single <tool> block could not be parsed into an executable call."""


@dataclass(frozen=True)
class ParsedTool:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


def parse_tools(text: str, *, strict: bool = False) -> list[ParsedTool]:
    """Extract every <tool>...</tool> call from an LLM response, in order.

    Malformed blocks are dropped (tolerant, runtime default) or raise
    ``ToolParseError`` naming the block (``strict=True``, for the dataset validator).
    """
    out: list[ParsedTool] = []
    for m in _BLOCK.finditer(text or ""):
        try:
            out.append(_parse_one(m.group(1)))
        except ToolParseError:
            if strict:
                raise
            # tolerant: skip this block, keep the valid siblings (fail-closed)
    return out


def _is_num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _at(rest: list[str], idx: int, inner: str, what: str) -> str:
    if idx >= len(rest):
        raise ToolParseError(f"{what} missing: {inner!r}")
    return rest[idx]


def _parse_one(inner: str) -> ParsedTool:
    toks = inner.split()
    if not toks:
        raise ToolParseError(f"empty tool call: {inner!r}")
    name, rest = toks[0], toks[1:]

    if name == "stop":
        args: dict[str, Any] = {}
    elif name == "scan_wifi":
        args = _parse_scan_wifi(rest, inner)
    elif name == "set_speed":
        args = {"level": _at(rest, 0, inner, "set_speed level")}
    elif name == "set_mode":
        args = {"mode": _at(rest, 0, inner, "set_mode mode")}
    elif name == "set_oracle":
        args = {"enabled": _parse_onoff(rest, inner)}
    elif name == "request_navigation_help":
        target = " ".join(rest)
        if not target:
            raise ToolParseError(f"request_navigation_help needs a target: {inner!r}")
        args = {"target": target}
    elif name == "camera":
        args = _parse_camera(rest, inner)
    elif name in ("move", "turn"):
        args = _parse_motion(name, rest, inner)
    else:
        # Unknown tool name — the KNOWN_TOOLS contract test guards the set; keep
        # the name so a caller/validator can see what the model tried to call.
        args = {}

    return ParsedTool(name, args)


def _parse_onoff(rest: list[str], inner: str) -> bool:
    if not rest or rest[0] not in ("on", "off"):
        raise ToolParseError(f"set_oracle expects on/off: {inner!r}")
    return rest[0] == "on"


def _parse_scan_wifi(rest: list[str], inner: str) -> dict[str, Any]:
    # read-only listing; optional whitelisted (filter|sort) VALUE pairs.
    # The model must not invent dict keys here — no injection surface (see spec).
    if len(rest) % 2 != 0:
        raise ToolParseError(f"scan_wifi args must be key/value pairs: {inner!r}")
    args: dict[str, Any] = {}
    for i in range(0, len(rest), 2):
        key = rest[i]
        if key not in _WIFI_KEYS:
            raise ToolParseError(f"scan_wifi unknown key {key!r}: {inner!r}")
        args[key] = rest[i + 1]
    return args


def _parse_camera(rest: list[str], inner: str) -> dict[str, Any]:
    if not rest:
        raise ToolParseError(f"camera needs an action or pan/tilt: {inner!r}")
    axis = rest[0]
    if axis in ("pan", "tilt"):
        direction = _at(rest, 1, inner, f"camera {axis} direction")
        valid = _PAN if axis == "pan" else _TILT
        if direction not in valid:
            raise ToolParseError(f"camera {axis} bad direction {direction!r}: {inner!r}")
        degrees = _at(rest, 2, inner, f"camera {axis} degrees")
        if not _is_num(degrees):
            raise ToolParseError(f"camera degrees not a number {degrees!r}: {inner!r}")
        return {axis: direction, "degrees": int(float(degrees))}
    # named gesture (action) — the enum contract test guards the value set.
    return {"action": axis}


def _parse_motion(name: str, rest: list[str], inner: str) -> dict[str, Any]:
    dirs = _MOVE_DIRS if name == "move" else _TURN_DIRS
    args: dict[str, Any] = {}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "until":
            args["until"] = _at(rest, i + 1, inner, f"{name} 'until' marker")
            i += 2
            continue
        if tok in dirs:
            args["direction"] = tok
        elif tok in _SPEEDS:
            args["speed"] = tok
        elif tok in _MODES:
            args["mode"] = tok
        elif _is_num(tok):
            args["degrees" if name == "turn" else "distance"] = (
                int(float(tok)) if name == "turn" else float(tok))
        else:
            # Unknown / mis-spelled / wrong-tool direction word — fail closed
            # rather than silently drop it into a directionless motor command.
            raise ToolParseError(f"{name}: unknown token {tok!r}: {inner!r}")
        i += 1
    return args
