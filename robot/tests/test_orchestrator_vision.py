"""A látás bekötése a körbe.

A tétel: a látás SOSEM viheti el a kört, és a látás HIÁNYA is eljut a modellhez.
"""

from __future__ import annotations

import dataclasses

from freedroid.config.settings import Settings, VisionSettings
from freedroid.orchestrator import Orchestrator
from freedroid.rag.context import LATVANY_NINCS


class HamisLLM:
    def __init__(self) -> None:
        self.promptok: list[str] = []

    def generate(self, prompt: str) -> str:
        self.promptok.append(prompt)
        return "Egy asztalt látok, Teremtőm."

    def active_backend(self):
        return None


class HamisVLM:
    def __init__(self, leiras: str | None = "A room with a table.") -> None:
        self._leiras = leiras
        self.hivasok = 0

    def describe(self, jpeg: bytes) -> str | None:
        self.hivasok += 1
        return self._leiras


class Csonk:
    """Motor/watchdog helyett: minden hívása némán elnyelődik."""

    def __getattr__(self, _nev):
        return lambda *a, **kw: None

    heading = None
    is_turning = False


def orch(monkeypatch, vlm, *, kep: bytes | None = b"\xff\xd8kep\xff\xd9") -> Orchestrator:
    monkeypatch.setattr("freedroid.camera.frame.grab_jpeg", lambda **kw: kep)
    beallitas = dataclasses.replace(
        Settings(), vision=VisionSettings(enabled=True, model="hamis-vlm:latest"))
    return Orchestrator(settings=beallitas, llm=HamisLLM(), vlm=vlm, camera=None,
                        motion=Csonk(), watchdog=Csonk())


def test_a_latas_kerdes_kap_LATVANY_blokkot(monkeypatch):
    vlm = HamisVLM()
    o = orch(monkeypatch, vlm)
    o.ask("Mit látsz?")
    assert vlm.hivasok == 1
    assert "[LÁTVÁNY]" in o.llm.promptok[0]
    assert "A room with a table." in o.llm.promptok[0]


def test_a_NEM_latas_kerdes_meg_sem_hivja_a_VLM_et(monkeypatch):
    """A képfeltöltés 2-3 másodperc — parancsra ne menjen el."""
    vlm = HamisVLM()
    o = orch(monkeypatch, vlm)
    o.ask("Szabi, gyere ide!")
    assert vlm.hivasok == 0
    assert "[LÁTVÁNY]" not in o.llm.promptok[0]


def test_ha_NINCS_kepkocka_akkor_a_NEGATIV_blokk_megy(monkeypatch):
    """🔴 Ez a hazugság elleni védelem: a néma kihagyás pontosan az az állapot,
    amiben a modell konfabulált."""
    vlm = HamisVLM()
    o = orch(monkeypatch, vlm, kep=None)
    o.ask("Mit látsz?")
    assert vlm.hivasok == 0, "kép nélkül nincs mit leírni"
    assert LATVANY_NINCS in o.llm.promptok[0]


def test_ha_a_VLM_nem_felel_akkor_is_a_NEGATIV_blokk(monkeypatch):
    o = orch(monkeypatch, HamisVLM(leiras=None))
    o.ask("Mit látsz?")
    assert LATVANY_NINCS in o.llm.promptok[0]


def test_a_latas_osszeomlasa_NEM_viszi_el_a_kort(monkeypatch):
    """Egy kivétel a látás-ágon nem némíthatja el a robotot."""
    class Robbano:
        def describe(self, jpeg):
            raise RuntimeError("boom")

    o = orch(monkeypatch, Robbano())
    valasz = o.ask("Mit látsz?")
    assert valasz, "a kör elhalt egy látás-hiba miatt"
    assert LATVANY_NINCS in o.llm.promptok[0]
