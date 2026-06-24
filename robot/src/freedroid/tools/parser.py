"""Parser for the LLM tool-calling grammar.

Format (from the training dataset): ``<tool>fn(key=value, ...)</tool>``
String values are quoted, numbers are bare. Multiple calls per response are allowed.
Examples:
    <tool>move(direction="forward", distance=2.0)</tool>
    <tool>turn(direction="left", degrees=90)</tool>
    <tool>stop()</tool>
    <tool>camera(action="face_speaker")</tool>
    <tool>scan_wifi()</tool>

The parser must be robust: tolerate extra whitespace and quote variants.
Interface + stub only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedTool:
    name: str
    args: dict[str, Any]


def parse_tools(text: str) -> list[ParsedTool]:
    """Extract every <tool>...</tool> call from an LLM response. STUB."""
    raise NotImplementedError("Phase 4.1: implement robust <tool> parser")
