"""Tool handler registry — maps a parsed tool name to a deterministic action.

Known tools (from the dataset): move, turn, stop, camera, set_speed, set_mode,
request_navigation_help, scan_wifi.

Safety rule: scan_wifi() is READ-ONLY — it runs
``nmcli -t -f SSID,SIGNAL,SECURITY dev wifi`` and returns the parsed list. It must
never connect to a network or handle a password.
Interface + stub only.
"""

from __future__ import annotations

from typing import Any, Callable

from freedroid.tools.parser import ParsedTool

Handler = Callable[[dict[str, Any]], Any]


class ToolRegistry:
    """Dispatches ParsedTool -> handler. STUB."""

    def __init__(self, motion=None, camera=None) -> None:
        raise NotImplementedError("Phase 4.1: wire handlers to motion/camera/wifi")

    def register(self, name: str, handler: Handler) -> None:
        raise NotImplementedError

    def dispatch(self, tool: ParsedTool) -> Any:
        raise NotImplementedError


def scan_wifi(_args: dict[str, Any]) -> list[dict[str, str]]:
    """READ-ONLY Wi-Fi listing via nmcli. Never connects. STUB."""
    raise NotImplementedError("Phase 4.1: parse `nmcli -t -f SSID,SIGNAL,SECURITY dev wifi`")
