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
#
# ⚠️ A `fast` NEM ízlés kérdése, hanem BIZTONSÁGI KORLÁT — mérve 2026-08-26, teli akkun,
# a watchdoggal együtt (`scripts/watchdog_e2e.py`). A watchdog döntéséig eltelő idő
# felső korlátja terhelés alatt 386 ms, és ez alatt a robot a 25 cm-es stop-küszöbből
# elhasznál `v * 0.386` cm-t, MIELŐTT a `stop()` egyáltalán lefutna:
#
#     0.8 duty -> 53 cm/s névlegesen (valósan ~61) -> 20-24 cm a 25-ből  ->  NEKIMEGY
#     0.6 duty -> 40 cm/s névlegesen (valósan ~46) -> 15-18 cm a 25-ből  ->  belefér
#
# Miért a sebességet fogjuk vissza, és nem a küszöböt emeljük: a küszöb FIZIKAI
# biztonsági távolság, a `fast` viszont egy kényelmi fokozat — és a szót a MODELL is
# kimondhatja (`<tool>move forward 2 fast</tool>` a nyelvtan része), tehát viselkedési
# szabállyal ("a demón ne mondjunk fast-ot") nem lehet kikényszeríteni.
#
# A "valósan" számok a névleges fölött vannak, mert a `cm_per_s_at_full = 66.6`
# kalibráció 2026-08-17-i, és FRISSEN TÖLTÖTT akkun a robot ~16%-kal gyorsabb (a
# közelítés nyoma szerint 38,5 cm/s a névleges 33,3 helyett `normal`-on).
SPEED_DUTY: dict[Speed, float] = {
    Speed.SLOW: 0.3,
    Speed.NORMAL: 0.5,
    Speed.FAST: 0.6,
}
