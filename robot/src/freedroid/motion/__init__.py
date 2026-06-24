"""Motion control — the deterministic "body" layer (Cytron HAT-MDD10 via lgpio).

The LLM never calls this directly; the tools layer does, after parsing a <tool> call.
Interface + stub only.
"""

from __future__ import annotations

from typing import Protocol


class MotionController(Protocol):
    """Deterministic motor control. All methods are safe to call from the tool layer."""

    def move(self, direction: str = "forward", distance: float | None = None,
             speed: float | None = None) -> None: ...

    def turn(self, direction: str, degrees: float) -> None: ...

    def stop(self) -> None: ...

    def set_speed(self, speed: float) -> None: ...


class CytronMotionController:
    """lgpio-backed implementation (Pi-only). STUB."""

    def __init__(self, settings=None) -> None:
        raise NotImplementedError("Phase 4.1: implement lgpio Cytron HAT-MDD10 control")

    def move(self, direction: str = "forward", distance: float | None = None,
             speed: float | None = None) -> None:
        raise NotImplementedError

    def turn(self, direction: str, degrees: float) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_speed(self, speed: float) -> None:
        raise NotImplementedError
