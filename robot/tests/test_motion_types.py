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
# (`scripts/watchdog_e2e.py`, 2026-08-26). A korábbi 0.467 még azt a watchdogot mérte,
# amelyik MINDKÉT szenzort lekérdezte körönként; mióta menet közben csak a haladási
# irány szenzorát méri, a korlát 223-233 ms. Felkerekítve.
WATCHDOG_FELSO_KORLAT_S = 0.25

# A LÁNCTALP KIFUTÁSA a `stop()` UTÁN. Ez a tag sokáig HIÁNYZOTT a modellből, és a
# 2026-08-26-i éles menet mutatta meg: a watchdog 17,2 cm-nél döntött, a `stop()`
# 0,2 ms alatt lefutott, a robot mégis 10,1 cm-nél állt meg — 7,1 cm-t ment még.
# Három menet adata: 2,9 cm @ 23 cm/s, 4,0 cm @ 38 cm/s, 7,1 cm @ 38 cm/s MÁS PADLÓN
# (= 126 / 104 / 185 ms). Tehát a felület számít, és a legrosszabbat vesszük.
# A kifutás nélkül a büdzsé a valóság ~60%-át számolta volna — épp a veszélyes irányban.
KIFUTAS_S = 0.20

# Felület- és mérési tartalék. NEM akku-tartalék többé, és ez fontos: a kalibráció a
# LEGGYORSABB állapotban készült (teli akku), a merülő akku pedig LASSÍT — az a hiba
# tehát a biztonságos irányba mutat. A korábbi 1.25 azért volt ekkora, mert a
# kalibráció 15%-kal elavult volt; ez az indok elfogyott.
TARTALEK = 1.10


def test_a_leggyorsabb_fokozat_belefer_a_fekutba():
    """A LEGFONTOSABB szám ebben a fájlban: a `fast` csak addig mehet, amíg a teljes
    fékút — a watchdog DÖNTÉSE plusz a lánctalp KIFUTÁSA — elfér a stop-küszöbben.

    Ez a teszt NÉGY értéket köt össze (duty, sebesség-kalibráció, watchdog-korlát,
    stop-küszöb). Bármelyik megemelése külön-külön ártatlannak látszik — a robot mégis
    nekimegy a falnak, mert a négyet senki nem nézi együtt. Ha elbukik, a válasz NEM a
    küszöb csökkentése: vagy a duty megy vissza, vagy újra kell mérni
    (`scripts/watchdog_e2e.py --live-motion`).
    """
    v_cm_s = MotionSettings().cm_per_s_at_full * SPEED_DUTY[Speed.FAST] * TARTALEK
    fekut_cm = v_cm_s * (WATCHDOG_FELSO_KORLAT_S + KIFUTAS_S)
    assert fekut_cm < SafetySettings().stop_threshold_cm, (
        f"{SPEED_DUTY[Speed.FAST]} kitöltésen a teljes fékút {fekut_cm:.1f} cm, a küszöb "
        f"{SafetySettings().stop_threshold_cm:.0f} cm")


def test_enums_are_str_backed():
    # str-Enum so a parsed string resolves directly: Direction("forward")
    assert Direction("forward") is Direction.FORWARD
    assert TurnDir("left") is TurnDir.LEFT
    assert Mode("approach_speaker") is Mode.APPROACH_SPEAKER
    assert StopCond("obstacle") is StopCond.OBSTACLE
