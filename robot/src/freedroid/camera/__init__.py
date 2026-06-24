"""Camera pan/tilt control — MG996R servos on the PCA9685 (distinct from the
track motors in `motion`). Driven by the `camera(...)` tool.
Interface + stub only.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from freedroid.config.settings import Settings


class CameraAction(str, Enum):
    """`camera(action=...)` — composite gestures."""
    FACE_SPEAKER = "face_speaker"
    NOD = "nod"
    SCAN = "scan"


class CameraController(Protocol):
    """Pan/tilt + named gestures. Mirrors the camera tool grammar."""

    def pan(self, direction: str, degrees: float) -> None: ...
    def tilt(self, direction: str, degrees: float) -> None: ...
    def action(self, action: CameraAction) -> None: ...


class PanTiltCamera:
    """PCA9685-backed implementation (Pi-only). STUB."""

    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.1: implement PCA9685 pan/tilt control")

    def pan(self, direction: str, degrees: float) -> None:
        raise NotImplementedError

    def tilt(self, direction: str, degrees: float) -> None:
        raise NotImplementedError

    def action(self, action: CameraAction) -> None:
        raise NotImplementedError
