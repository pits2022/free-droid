"""Parser for the LLM tool-calling grammar.

Format (from the training dataset): ``<tool>fn(arg, ...)</tool>`` where each arg is
either ``key=value`` or a bare positional value. String values are quoted, numbers
are bare. Multiple calls per response are allowed. Examples seen in the dataset:
    <tool>move(direction="forward", distance=2.0)</tool>
    <tool>move(mode="approach_speaker")</tool>           # keyword-only, no direction
    <tool>turn(mode="face_audience")</tool>
    <tool>set_mode("standby")</tool>                      # POSITIONAL arg
    <tool>scan_wifi(filter="wpa3", sort="signal")</tool>
    <tool>stop()</tool>

The parser must be robust: tolerate extra whitespace and quote variants. It captures
positional args too, so callers can normalise them per-tool (e.g. set_mode's first
positional -> mode=).
Interface + stub only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedTool:
    name: str
    args: dict[str, Any] = field(default_factory=dict)        # key=value args
    positional: tuple[Any, ...] = ()                           # bare args, in order


def parse_tools(text: str) -> list[ParsedTool]:
    """Extract every <tool>...</tool> call from an LLM response. STUB."""
    raise NotImplementedError("Phase 4.1: implement robust <tool> parser")
