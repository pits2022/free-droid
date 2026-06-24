"""motion.types — enum domains and the qualitative-speed -> duty mapping."""

from __future__ import annotations

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


def test_enums_are_str_backed():
    # str-Enum so a parsed string resolves directly: Direction("forward")
    assert Direction("forward") is Direction.FORWARD
    assert TurnDir("left") is TurnDir.LEFT
    assert Mode("approach_speaker") is Mode.APPROACH_SPEAKER
    assert StopCond("obstacle") is StopCond.OBSTACLE
