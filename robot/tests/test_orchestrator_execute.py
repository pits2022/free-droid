"""Az orchestrátor VÉGREHAJTÁSI útja: modell-válasz -> tool-ok + kimondandó szöveg.

Ez a lánc az, ami a hang és az LLM nélkül is teljes (Phase 4.1), tehát ez az, amit
hardveren ma ki lehet próbálni. A `guard()` saját tesztjei külön élnek — itt az a
tétel, hogy az orchestrátor a guard eredményét HELYESEN hajtja végre.
"""

from __future__ import annotations

import pytest

from freedroid.motion.types import Direction
from freedroid.orchestrator import BIZTONSAGI_ELHARITAS, Orchestrator


class FakeMotion:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.heading: Direction | None = None
        self.is_turning = False
        self.closed = False

    def move(self, **kw) -> None:
        self.calls.append("move")

    def turn(self, **kw) -> None:
        self.calls.append("turn")

    def stop(self) -> None:
        self.calls.append("stop")

    def set_speed(self, speed) -> None:
        self.calls.append("set_speed")

    def close(self) -> None:
        self.closed = True


class FakeWatchdog:
    def __init__(self, fault: str | None = None) -> None:
        self.fault = fault
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop_monitoring(self) -> None:
        self.stopped = True

    def distances_cm(self) -> dict[str, float | None]:
        return {}

    def is_blocked(self) -> bool:
        return False


def orch(fault: str | None = None) -> tuple[Orchestrator, FakeMotion]:
    m = FakeMotion()
    return Orchestrator(motion=m, watchdog=FakeWatchdog(fault)), m


def test_a_tool_fut_es_a_szoveg_markup_nelkul_jon_vissza():
    o, m = orch()
    assert o.execute("Megyek, Teremtőm. <tool>move forward 2</tool>") == "Megyek, Teremtőm."
    assert m.calls == ["move"]


def test_kitalalt_tool_nem_hajtodik_vegre_es_elharitast_mond():
    """A mért `wf_03`: a felsorolás jogos, a csatlakozás nem — a robot elhárít."""
    o, m = orch()
    beszed = o.execute("Rálépek a legerősebbre. <tool>connect_to_best_network x</tool>")
    assert "Hálózatra nem lépek fel" in beszed
    assert m.calls == []


def test_hibas_watchdog_letiltja_a_MOZGAST():
    o, m = orch(fault="OSError('lgpio')")
    assert o.execute("<tool>move forward 2</tool>") == BIZTONSAGI_ELHARITAS
    assert m.calls == []


def test_hibas_watchdog_mellett_a_STOP_MEGIS_fut():
    """Megállni mindig szabad — egy hibás watchdog nem tilthatja meg a fékezést."""
    o, m = orch(fault="OSError('lgpio')")
    o.execute("<tool>stop</tool>")
    assert m.calls == ["stop"]


def test_egy_elbukott_tool_utan_a_robot_MEGSZOLAL():
    """A néma robot a színpadon halott robot — a hiba a naplóba megy, nem a beszéd elé."""
    o, m = orch()
    # `camera` vezérlő nincs bekötve (a szervókra vár) -> a dispatch LookupError-t dob.
    beszed = o.execute("Odanézek. <tool>camera pan left 45</tool>")
    assert beszed == "Odanézek."


def test_tobb_tool_sorrendben_fut():
    o, m = orch()
    o.execute("<tool>turn left 90</tool><tool>move forward 1</tool>")
    assert m.calls == ["turn", "move"]


def test_start_inditja_a_watchdogot_close_lezar_mindent():
    o, m = orch()
    o.start()
    assert o.watchdog.started is True
    o.close()
    assert o.watchdog.stopped is True and m.closed is True


def test_a_hurok_meg_NEM_letezik_es_ezt_hangosan_mondja():
    """A `run()` a voice/llm stubokra vár. Ha valaki megírja, ez a teszt szól, hogy
    frissítse — egy csendben no-oppá vált hurok sokkal rosszabb lenne."""
    o, _ = orch()
    with pytest.raises(NotImplementedError):
        import asyncio
        asyncio.run(o.run())
