"""Tool handler registry — maps a parsed tool name to a deterministic action.

Known tools (from the dataset): move, turn, stop, camera, set_speed, set_mode,
request_navigation_help, scan_wifi.

Safety rule: scan_wifi() is READ-ONLY — it runs
``nmcli -t -f SSID,SIGNAL,SECURITY dev wifi`` and returns the parsed list. It must
never connect to a network or handle a password.
Interface + stub only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from freedroid.tools.parser import ParsedTool

if TYPE_CHECKING:
    from freedroid.camera import CameraController
    from freedroid.motion import MotionController

Handler = Callable[[ParsedTool], Any]


class ToolRegistry:
    """Dispatches ParsedTool -> handler. STUB.

    Resolves raw arg strings into the motion/camera enums and maps qualitative
    speed -> PWM duty (via motion.types.SPEED_DUTY) before calling the controllers.
    """

    def __init__(self, motion: MotionController | None = None,
                 camera: CameraController | None = None) -> None:
        raise NotImplementedError("Phase 4.1: wire handlers to motion/camera/wifi")

    def register(self, name: str, handler: Handler) -> None:
        raise NotImplementedError

    def dispatch(self, tool: ParsedTool) -> Any:
        raise NotImplementedError


def scan_wifi(tool: ParsedTool) -> list[dict[str, str]]:
    """READ-ONLY Wi-Fi listing via nmcli. Never connects. STUB.

    Optional display-only args (from the grammar): filter="wpa3", sort="signal".
    These only shape the returned list — they never trigger a connection.
    """
    raise NotImplementedError("Phase 4.1: parse `nmcli -t -f SSID,SIGNAL,SECURITY dev wifi`")
