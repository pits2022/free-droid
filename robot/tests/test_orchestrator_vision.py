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
    def __init__(self, leiras: str | None = "A room with a table.",
                 elerheto: tuple[bool, str] = (True, "elérhető")) -> None:
        self._leiras = leiras
        self._elerheto = elerheto
        self.hivasok = 0

    def describe(self, jpeg: bytes) -> str | None:
        self.hivasok += 1
        return self._leiras

    def elerheto(self) -> tuple[bool, str]:
        return self._elerheto


class Csonk:
    """Motor/watchdog helyett: minden hívása némán elnyelődik."""

    def __getattr__(self, _nev):
        return lambda *a, **kw: None

    heading = None
    is_turning = False


def orch(monkeypatch, vlm, *, kep: bytes | None = b"\xff\xd8kep\xff\xd9") -> Orchestrator:
    monkeypatch.setattr("freedroid.camera.frame.grab_jpeg", lambda *a, **kw: kep)
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

        def elerheto(self):
            return True, "elérhető"

    o = orch(monkeypatch, Robbano())
    valasz = o.ask("Mit látsz?")
    assert valasz, "a kör elhalt egy látás-hiba miatt"
    assert LATVANY_NINCS in o.llm.promptok[0]


def test_ha_a_vlm_nem_epult_meg_a_latas_kerdes_NEGATIV_blokkot_kap(monkeypatch):
    """C1 (végső review, KRITIKUS): a `self.vlm is None` és a "nem látás-kérdés" eddig
    UGYANABBA az ágba folyt — egy shadow deployban elmaradt `vision/` szinkron esetén ez
    NÉMÁN engedte volna a kérdést a modellhez, kép nélkül, szabadon konfabulálhatóan.
    A `self.vlm is None` a realisztikus eset: a `_vlm()` hibatűrő, tehát ez pont az az
    állapot, amiben a modul konstrukciója elhasalt."""
    o = orch(monkeypatch, HamisVLM())
    o.vlm = None
    o.ask("Mit látsz?")
    assert LATVANY_NINCS in o.llm.promptok[0]


def test_ha_a_vlm_nem_epult_meg_a_NEM_latas_kerdes_erintetlen_marad(monkeypatch):
    """C1 ellenpróbája: a `vlm is None` eset se nyúljon bele egy NEM látás-kérdés
    promptjába — a `None`/`LATVANY_NINCS` különbség csak a látás-kérdésekre él."""
    o = orch(monkeypatch, HamisVLM())
    o.vlm = None
    o.ask("Szabi, gyere ide!")
    assert "[LÁTVÁNY]" not in o.llm.promptok[0]


def test_ha_a_vlm_NEM_ELERHETO_akkor_negativ_blokk_es_NINCS_kepfeltoltes(monkeypatch):
    """I1 (végső review, FONTOS): a `korben_elerhetetlen` kör-cache-t eddig semmi nem
    konzultálta a látás-ágon — egy halott alagút mellett a régi kód levágott egy
    képkockát (0.4-1.6 s), majd a TELJES `timeout_s`-t (8 s) is kivárta a hívásban:
    ~9 s néma színpadi csend egy olyan tényre, amit az STT/LLM próbája a körben már
    megállapított. Az `elerheto()`-nak a `grab_jpeg` ELŐTT kell futnia."""
    grab_hivasok: list[object] = []
    monkeypatch.setattr("freedroid.camera.frame.grab_jpeg",
                        lambda *a, **kw: grab_hivasok.append(1) or b"\xff\xd8kep\xff\xd9")
    vlm = HamisVLM(elerheto=(False, "nem elérhető (teszt)"))
    beallitas = dataclasses.replace(
        Settings(), vision=VisionSettings(enabled=True, model="hamis-vlm:latest"))
    o = Orchestrator(settings=beallitas, llm=HamisLLM(), vlm=vlm, camera=None,
                     motion=Csonk(), watchdog=Csonk())
    o.ask("Mit látsz?")
    assert grab_hivasok == [], "elérhetetlen VLM esetén nem szabad képkockát ragadni"
    assert vlm.hivasok == 0, "elérhetetlen VLM esetén a describe() sem hívódhat"
    assert LATVANY_NINCS in o.llm.promptok[0]


def test_a_kikapcsolt_latas_NEM_ragad_kepkockat(monkeypatch):
    """I3 (végső review, FONTOS): a `_vlm()` docstringje azt ígérte, hogy kikapcsolt
    látással `describe()` visszaadja `None`-t — de a `grab_jpeg` addigra MÁR lefutott
    (~1.6 s kamerawunka a semmiért). A valódi `CloudVLM` `elerheto()`-ja `enabled=False`
    esetén rögtön hamis, tehát az I1 sorrend-javítás ezt is megoldja: a kép fel sem
    kerül a kamerából, mielőtt eldobnánk."""
    from freedroid.vision import CloudVLM

    grab_hivasok: list[object] = []
    monkeypatch.setattr("freedroid.camera.frame.grab_jpeg",
                        lambda *a, **kw: grab_hivasok.append(1) or b"\xff\xd8kep\xff\xd9")
    beallitas = dataclasses.replace(
        Settings(), vision=VisionSettings(enabled=False, model=""))
    o = Orchestrator(settings=beallitas, llm=HamisLLM(), vlm=CloudVLM(beallitas),
                     camera=None, motion=Csonk(), watchdog=Csonk())
    o.ask("Mit látsz?")
    assert grab_hivasok == [], "kikapcsolt látással grab_jpeg nem futhat le"
    assert LATVANY_NINCS in o.llm.promptok[0]
