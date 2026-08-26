"""motion.types — enum domains and the qualitative-speed -> duty mapping."""

from __future__ import annotations

from freedroid.config.settings import MotionSettings, SafetySettings
from freedroid.motion.types import (
    SPEED_DUTY,
    Direction,
    Mode,
    Speed,
    StopCond,
    TurnDir,
)


def test_speed_duty_covers_every_speed():
    assert set(SPEED_DUTY) == set(Speed)


def test_speed_duty_values_are_valid_pwm_duty():
    for duty in SPEED_DUTY.values():
        assert 0.0 <= duty <= 1.0


def test_speed_duty_is_monotonic():
    assert SPEED_DUTY[Speed.SLOW] < SPEED_DUTY[Speed.NORMAL] < SPEED_DUTY[Speed.FAST]


# A watchdog döntéséig eltelő idő MÉRT felső korlátja, ollama-terhelés alatt, a Pi-n
# (`scripts/watchdog_e2e.py`, 2026-08-26, négy egyező futás: 365-467 ms).
WATCHDOG_FELSO_KORLAT_S = 0.467
# A kalibráció (2026-08-17) és a friss akku közti eltérés: a mért sebesség ~16%-kal
# nagyobb a névlegesnél. A 1.25 ezt fedi le, tartalékkal.
AKKU_TARTALEK = 1.25


def test_a_leggyorsabb_fokozat_belefer_a_watchdog_fektavjaba():
    """A LEGFONTOSABB szám ebben a fájlban: a `fast` csak addig mehet, amíg a watchdog
    döntéséig megtett út elfér a stop-küszöbben.

    Ez a teszt azt őrzi, hogy a három érték (duty, sebesség-kalibráció, stop-küszöb)
    EGYÜTT érvényes. Bármelyik megemelése külön-külön ártatlannak látszik — a robot
    mégis nekimegy a falnak, mert a hármat senki nem nézi együtt. Ha ez a teszt elbukik,
    a válasz nem a küszöb csökkentése: vagy a duty megy vissza, vagy újra kell mérni
    (`scripts/watchdog_e2e.py --live-motion`).
    """
    v_cm_s = MotionSettings().cm_per_s_at_full * SPEED_DUTY[Speed.FAST] * AKKU_TARTALEK
    dontesig_cm = v_cm_s * WATCHDOG_FELSO_KORLAT_S
    assert dontesig_cm < SafetySettings().stop_threshold_cm, (
        f"{SPEED_DUTY[Speed.FAST]} kitöltésen a robot {dontesig_cm:.1f} cm-t tesz meg a "
        f"watchdog döntéséig, a küszöb {SafetySettings().stop_threshold_cm:.0f} cm")


def test_enums_are_str_backed():
    # str-Enum so a parsed string resolves directly: Direction("forward")
    assert Direction("forward") is Direction.FORWARD
    assert TurnDir("left") is TurnDir.LEFT
    assert Mode("approach_speaker") is Mode.APPROACH_SPEAKER
    assert StopCond("obstacle") is StopCond.OBSTACLE
