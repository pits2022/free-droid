"""TDD harness for the hardware controllers (Phase 4.1).

These only run on a real Pi (skipped elsewhere) and xfail (strict) until the
lgpio/PCA9685 implementations land. On the Pi, an implemented controller turning
these green forces removing the xfail marker.
"""

from __future__ import annotations

import pytest

from freedroid.health.probe import is_pi
from freedroid.motion import CytronMotionController
from freedroid.motion.types import Direction, TurnDir
from freedroid.safety import UltrasonicWatchdog

requires_pi = pytest.mark.skipif(not is_pi(), reason="requires real Raspberry Pi hardware")
pytestmark = [requires_pi, pytest.mark.phase4]


@pytest.mark.xfail(reason="Phase 4.1: Cytron control not implemented", strict=True)
def test_motion_stop_is_safe_to_call():
    m = CytronMotionController()
    m.move(direction=Direction.FORWARD, distance=0.2)
    m.stop()  # must leave both motors at zero duty


@pytest.mark.xfail(reason="Phase 4.1: Cytron control not implemented", strict=True)
def test_turn_accepts_grammar_enums():
    CytronMotionController().turn(direction=TurnDir.LEFT, degrees=90)


@pytest.mark.xfail(reason="Phase 4.1: ultrasonic watchdog not implemented", strict=True)
def test_watchdog_reads_three_distances():
    triggered = []
    wd = UltrasonicWatchdog(on_obstacle=lambda: triggered.append(True))
    assert set(wd.distances_cm()) == {"front", "front_left", "front_right"}
