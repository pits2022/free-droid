"""Tool-calling: parse <tool> blocks and dispatch them to deterministic handlers."""

from freedroid.tools.handlers import ToolRegistry, scan_wifi
from freedroid.tools.parser import ParsedTool, parse_tools

__all__ = ["ParsedTool", "parse_tools", "ToolRegistry", "scan_wifi"]
