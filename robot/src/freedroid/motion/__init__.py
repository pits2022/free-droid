"""Motion control — the deterministic "body" layer (Cytron HAT-MDD10 via lgpio).

The LLM never calls this directly; the tools layer does, after parsing a <tool> call
and resolving raw strings into the enums in `motion.types`.
Interface + stub only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from freedroid.motion.types import Direction, Mode, Speed, StopCond, TurnDir

if TYPE_CHECKING:
    from freedroid.config.settings import Settings


class MotionController(Protocol):
    """Deterministic track control. Mirrors the move/turn/stop/set_speed tool grammar.

    All params are optional because the grammar allows mode-only forms
    (e.g. ``move(mode="approach_speaker")``, ``turn(mode="face_audience")``).
    """

    def move(self, direction: Direction | None = None, distance: float | None = None,
             speed: Speed | None = None, mode: Mode | None = None,
             until: StopCond | None = None) -> None: ...

    def turn(self, direction: TurnDir | None = None, degrees: float | None = None,
             mode: Mode | None = None) -> None: ...

    def stop(self) -> None: ...

    def set_speed(self, speed: Speed) -> None:
        """Set the default cruise speed (qualitative; resolved via types.SPEED_DUTY)."""
        ...


class CytronMotionController:
    """lgpio-backed implementation (Pi-only). STUB."""

    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.1: implement lgpio Cytron HAT-MDD10 control")

    def move(self, direction: Direction | None = None, distance: float | None = None,
             speed: Speed | None = None, mode: Mode | None = None,
             until: StopCond | None = None) -> None:
        raise NotImplementedError

    def turn(self, direction: TurnDir | None = None, degrees: float | None = None,
             mode: Mode | None = None) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_speed(self, speed: Speed) -> None:
        raise NotImplementedError
