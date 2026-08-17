"""TDD harness for the hardware controllers (Phase 4.1).

These only run on a real Pi (skipped elsewhere).

⚠️ A MOZGÁSSAL járó teszt KÜLÖN ENGEDÉLYT kér (`FREEDROID_MOTOR_TEST=1`). Egy sima
`uv run pytest` a roboton nem indíthatja el a lánctalpakat: a Pi-n a teszt gyakran
SSH-ból, felügyelet nélkül fut, és egy asztalon álló robot lehajt róla. A vezérelt,
felpolcolt mozgáspróba helye a `scripts/motor_test.py`, ahol az operátor szándékosan
indítja. Ami itt marad, az az, ami MOZGÁS NÉLKÜL is elromolhat: a lábak lefoglalása,
a megállás és az állapot, amit a watchdog olvas.
"""

from __future__ import annotations

import os

import pytest

from freedroid.config import gpio as G
from freedroid.health.probe import is_pi
from freedroid.motion import CytronMotionController
from freedroid.motion.types import Direction, Speed, TurnDir
from freedroid.safety import UltrasonicWatchdog

requires_pi = pytest.mark.skipif(not is_pi(), reason="requires real Raspberry Pi hardware")
allows_motion = pytest.mark.skipif(
    os.environ.get("FREEDROID_MOTOR_TEST") != "1",
    reason="mozgatja a robotot — FREEDROID_MOTOR_TEST=1 kell hozzá, felpolcolt robotnál",
)
pytestmark = [requires_pi, pytest.mark.phase4]


@pytest.fixture
def motion():
    m = CytronMotionController()
    yield m
    m.close()


@pytest.fixture
def watchdog():
    wd = UltrasonicWatchdog(on_obstacle=lambda: None)
    yield wd
    wd.close()


def test_stop_is_safe_before_any_move(motion):
    """A `stop()` hívható indulás előtt is — a watchdog bármikor meghívhatja."""
    motion.stop()
    assert motion.heading is None
    assert motion.is_turning is False


def test_speed_change_does_not_start_the_motors(motion):
    """A `set_speed` csak a következő menetre hat, magától nem indít."""
    motion.set_speed(Speed.FAST)
    assert motion.heading is None


@allows_motion
def test_move_and_turn_accept_grammar_enums(motion):
    """Az egyetlen MOZGÓ teszt — felpolcolt robotnál, szándékos engedéllyel."""
    motion.move(direction=Direction.FORWARD, distance=0.2)
    assert motion.heading is None  # a menet végén megáll
    motion.turn(direction=TurnDir.LEFT, degrees=90)
    assert motion.is_turning is False


def test_watchdog_reports_every_configured_sensor(watchdog):
    assert set(watchdog.distances_cm()) == set(G.ULTRASONIC)


def test_watchdog_measures_both_sensors(watchdog):
    """Egy kör után MINDKÉT szenzornak mérnie kell.

    A None itt NÉMA szenzort jelent (szakadt vezeték, nincs táp) — a szabad utat az
    `inf` jelzi. Ez a teszt tehát a bekötést fogja meg, nem a távolságot.
    """
    watchdog.poll_once()
    assert all(cm is not None for cm in watchdog.distances_cm().values()), \
        f"néma szenzor: {watchdog.distances_cm()}"
