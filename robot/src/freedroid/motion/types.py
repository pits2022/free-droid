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
# ⚠️ A `fast` NEM ízlés kérdése, hanem BIZTONSÁGI KORLÁT — mérve 2026-08-26, teli
# akkun, a watchdoggal együtt (`scripts/watchdog_e2e.py`). A watchdog döntéséig eltelő
# idő felső korlátja terhelés alatt 223 ms, és ez alatt a robot a 25 cm-es stop-
# küszöbből elhasznál `v * T` cm-t, MIELŐTT a `stop()` egyáltalán lefutna. A mai
# kalibrációval (76,6 cm/s teljes kitöltésen), 1,25-ös akku/padló-tartalékkal:
#
#     0.6 duty -> 46 cm/s -> 14,4 cm a 25-ből  ->  10,6 cm marad a fékútra
#     0.8 duty -> 61 cm/s -> 19,2 cm a 25-ből  ->   5,8 cm marad
#
# MIÉRT MARAD 0.6, holott a 0.8 is beleférne. Két lépésben jutottunk ide, és a sorrend
# tanulságos: először a SEBESSÉGET fogtuk vissza (0.8 -> 0.6), mert az akkori watchdog
# 467 ms-os korláttal a 0.8-on nekiment volna. Utána a GYÖKÉROKOT javítottuk — menet
# közben a watchdog csak a haladási irány szenzorát méri, lásd `safety/__init__.py` —,
# és a korlát 223 ms-ra esett. A 0.8 ettől beleférne, de a demó nem kíván 61 cm/s-ot
# egy közönség között mozgó roboton, és a 10,6 cm tartalék többet ér, mint a sebesség.
# Ez tehát MÉRLEGELÉS, nem kényszer: ha valaha kell a gyorsabb fokozat, a szám
# emelhető — de CSAK a `test_a_leggyorsabb_fokozat_belefer_a_watchdog_fektavjaba`
# újrafuttatásával és egy friss `--live-motion` méréssel.
#
# MIÉRT A SEBESSÉG, ÉS NEM A KÜSZÖB. A küszöb fizikai biztonsági távolság; a `fast`
# kényelmi fokozat. Ráadásul a szót a MODELL is kimondhatja (`move forward 2 fast` a
# nyelvtan része), tehát viselkedési szabállyal ("a demón ne mondjunk fast-ot") nem
# lehet kikényszeríteni.
SPEED_DUTY: dict[Speed, float] = {
    Speed.SLOW: 0.3,
    Speed.NORMAL: 0.5,
    Speed.FAST: 0.6,
}
