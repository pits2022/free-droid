"""Státusz-gyűrű: a spec §6 leképezése az orchestrátor állapotából + tiszta képkockák."""
from __future__ import annotations

import pytest

from freedroid import led
from freedroid.led import LedController, NullRing, Pattern, Scene, frame
from freedroid.orchestrator import Orchestrator, State


class HamisMotion:
    heading, is_turning = None, False

    def stop(self) -> None: ...

    def close(self) -> None: ...


class HamisWatchdog:
    fault = None

    def start(self) -> None: ...

    def stop_monitoring(self) -> None: ...


class HamisLLM:
    def __init__(self, backend=None) -> None:
        self._b = backend

    def active_backend(self):
        return self._b


def robot(backend=None) -> Orchestrator:
    o = Orchestrator(motion=HamisMotion(), watchdog=HamisWatchdog(), llm=HamisLLM(backend),
                     led=LedController(NullRing(), lambda: led.OFF, 12))
    return o


@pytest.mark.parametrize("state, backend, pattern, color", [
    (State.LISTENING, None, Pattern.BREATHE, led.WHITE),
    (State.RECORDING, None, Pattern.PULSE, led.GREEN),
    (State.THINKING, "cloud", Pattern.SPIN, led.BLUE),
    (State.THINKING, "edge", Pattern.SPIN, led.PURPLE),
    (State.THINKING, None, Pattern.SPIN, led.WHITE),      # még nem felelt senki
    (State.SPEAKING, "edge", Pattern.SOLID, led.PURPLE),
    (State.SAFE_MODE, "cloud", Pattern.SOLID, led.RED),
])
def test_spec_6_lekepezes(state, backend, pattern, color):
    o = robot(backend)
    o.state = state
    assert o._led_scene() == Scene(pattern, color)


def test_prioritas_tiltas_mozgas_akku():
    o = robot("cloud")
    o.state = State.LISTENING
    o._akku_gyenge = True
    assert o._led_scene() == Scene(Pattern.BREATHE, led.ORANGE)   # gyenge akku: narancs lélegzés
    o.motion.heading = "forward"
    assert o._led_scene() == Scene(Pattern.CHASE, led.WHITE, direction=1)   # mozgás a lélegzés fölött
    o.motion.heading = "backward"
    assert o._led_scene().direction == -1                           # hátra: a futófény is (PR #105)
    o._akku_kritikus = True
    assert o._led_scene() == led.SAFE                               # tiltás mindenek fölött


def test_akadaly_villanas_felulir_aztan_lejar():
    o = robot()
    o.state = State.SPEAKING
    o.led._scene_fn = o._led_scene
    o._akadaly()                                                    # a watchdog reflexe
    assert o.led.current().pattern is Pattern.FLASH
    assert o.led.current(now=o.led._override[1] + 0.01).pattern is Pattern.SOLID


def test_frame_tiszta_es_ertelmes():
    n = 12
    assert frame(led.OFF, 0.0, n) == [led.BLACK] * n
    assert frame(Scene(Pattern.SOLID, led.RED), 5.0, n) == [led.RED] * n
    spin0, spin_half = frame(Scene(Pattern.SPIN, led.BLUE), 0.0, n), frame(Scene(Pattern.SPIN, led.BLUE), 0.5, n)
    assert spin0.index(max(spin0)) == 0 and spin_half.index(max(spin_half)) == 6   # a fej körbejár
    assert frame(Scene(Pattern.SPIN, led.BLUE), 0.0, n) == spin0                    # determinisztikus
    assert max(max(p) for p in frame(Scene(Pattern.BREATHE, led.WHITE), 0.0, n)) < 128   # tényleg halvány
    on, off = frame(led.OBSTACLE, 0.05, n), frame(led.OBSTACLE, 0.25, n)
    assert on[0] == led.RED and off[0] == led.BLACK                                 # villan
    assert len({p for p in frame(led.BOOT_OK, 0.0, n)}) == n                       # szivárvány: mind más
