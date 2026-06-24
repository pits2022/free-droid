"""Closed value domains for the motion/tool grammar.

Derived from the actual tool calls in training/dataset/ (not invented). The parser
stays tolerant of raw strings; these enums are resolved at the parser/handler
boundary so an unknown value fails loudly instead of becoming a motor no-op.
"""

from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    """`move(direction=...)`."""
    FORWARD = "forward"
    BACKWARD = "backward"


class TurnDir(str, Enum):
    """`turn(direction=...)`."""
    LEFT = "left"
    RIGHT = "right"


class Speed(str, Enum):
    """Qualitative speed from the LLM (`move(speed=...)`, `set_speed(level=...)`)."""
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"


class Mode(str, Enum):
    """Behaviour modes (`move`/`turn`/`set_mode`). Open-ended — may grow with the dataset."""
    APPROACH_SPEAKER = "approach_speaker"
    FOLLOW_SPEAKER = "follow_speaker"
    FACE_AUDIENCE = "face_audience"
    STANDBY = "standby"


class StopCond(str, Enum):
    """`move(until=...)` — stop condition handed to the safety layer."""
    OBSTACLE = "obstacle"


# The one typed home for the qualitative-speed -> PWM-duty mapping.
SPEED_DUTY: dict[Speed, float] = {
    Speed.SLOW: 0.3,
    Speed.NORMAL: 0.5,
    Speed.FAST: 0.8,
}
