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
    def __init__(self, fault: str | None = None, leallas_hiba: bool = False) -> None:
        self.fault = fault
        self.started = False
        self.stopped = False
        self._leallas_hiba = leallas_hiba

    def start(self) -> None:
        self.started = True

    def stop_monitoring(self) -> None:
        self.stopped = True
        if self._leallas_hiba:
            raise RuntimeError("a szál-join elhasalt")

    def distances_cm(self) -> dict[str, float | None]:
        return {}

    def is_blocked(self) -> bool:
        return False


class FakeCamera:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def pan(self, direction, degrees) -> None:
        self.calls.append("pan")

    def tilt(self, direction, degrees) -> None:
        self.calls.append("tilt")

    def action(self, action) -> None:
        self.calls.append("action")

    def close(self) -> None:
        pass


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


# --- PR #85 review ---

@pytest.mark.parametrize("valasz", [
    "<tool>camera nod</tool><tool>move forward 2</tool>",
    "<tool>move forward 2</tool><tool>camera nod</tool>",
])
def test_hibas_watchdog_mellett_a_KOTEG_egeszet_eldobjuk(valasz):
    """A tiltás ne legyen SORRENDFÜGGŐ.

    A menet közbeni döntés mellett a `[camera, move]` válasznál a kamera még lefutott,
    a `[move, camera]`-nál nem — ugyanarra a kérésre. Egy kis modell tool-sorrendje
    nem stabil, tehát ez futásonként változó viselkedés lett volna, pont abban az
    állapotban, amikor a robot már nem lát tisztán.
    """
    c = FakeCamera()
    m = FakeMotion()
    o = Orchestrator(motion=m, camera=c, watchdog=FakeWatchdog(fault="OSError('lgpio')"))
    assert o.execute(valasz) == BIZTONSAGI_ELHARITAS
    assert m.calls == [] and c.calls == []


def test_close_lezarja_a_vezerloket_akkor_is_ha_a_watchdog_elhasal():
    """A legrosszabb kimenet: járó lánctalpak egy kilépő folyamat után."""
    m = FakeMotion()
    o = Orchestrator(motion=m, watchdog=FakeWatchdog(leallas_hiba=True))
    o.close()
    assert m.closed is True


# --- Phase 4.2: ask() — a teljes lánc hang nélkül ---

class FakeLLM:
    def __init__(self, valasz: str = "Megyek, Teremtőm.", hiba: Exception | None = None) -> None:
        self._valasz = valasz
        self._hiba = hiba
        self.promptok: list[str] = []
        self.melegitve = False

    def generate(self, prompt: str) -> str:
        self.promptok.append(prompt)
        if self._hiba is not None:
            raise self._hiba
        return self._valasz

    def active_backend(self):
        from freedroid.llm import Backend
        return Backend.CLOUD

    def active_model(self) -> str:
        return "csaba_ajtony/szabi-8b-v12"

    def decision(self) -> str:
        return "cloud: felelt (csaba_ajtony/szabi-8b-v12)"

    def warmup(self):
        self.melegitve = True


def kerdezo(llm: FakeLLM, monkeypatch, rag: bool = False):
    """Orchestrátor RAG és átirat-napló nélkül — itt a LÁNC a tétel, nem a mellékhatásai."""
    o = Orchestrator(motion=FakeMotion(), watchdog=FakeWatchdog(), llm=llm)
    monkeypatch.setattr("freedroid.orchestrator.transcript.log", lambda *a, **k: None)
    if not rag:
        monkeypatch.setattr(o, "_talalatok", lambda k: [])
    return o


def test_ask_vegigviszi_a_lancot(monkeypatch):
    llm = FakeLLM("Megyek, Teremtőm. <tool>move forward 2</tool>")
    o = kerdezo(llm, monkeypatch)
    assert o.ask("Gyere ide!") == "Megyek, Teremtőm."
    assert o.motion.calls == ["move"]
    assert llm.promptok == ["Gyere ide!"]   # forrás nélkül a prompt VÁLTOZATLAN


def test_ask_elteszi_a_HASZNALT_talalatokat(monkeypatch):
    """A FORRÁS-kiírás forrása UGYANAZ a lista, amit a prompt kapott.

    Az azonosság (`is`) a tétel, nem az egyenlőség: egy második lekérdezés egyenlő
    listát adna, de elcsúszhatna, ha a keresés valaha megváltozik (PR #93 review).
    """
    llm = FakeLLM("Ez az.")
    o = kerdezo(llm, monkeypatch, rag=True)
    import types
    sajat = [types.SimpleNamespace(
        chunk=types.SimpleNamespace(id="yot-000", title="ÁL-TALÁLAT"), score=1.0)]
    monkeypatch.setattr(o, "_talalatok", lambda k: sajat)
    monkeypatch.setattr("freedroid.orchestrator.build_prompt", lambda k, h: k)
    o.ask("Mi az a Yotengrit?")
    assert o.utolso_talalatok is sajat


def test_ask_safe_mode_ha_egyik_elme_sem_felel(monkeypatch):
    """A robot NEM némul el: a néma robot a színpadon megkülönböztethetetlen a lefagyottól."""
    from freedroid.llm import LLMUnavailable
    from freedroid.orchestrator import SAFE_MODE_VALASZ

    o = kerdezo(FakeLLM(hiba=LLMUnavailable("cloud: nem elérhető; edge: nem elérhető")),
                monkeypatch)
    assert o.ask("Ki vagy?") == SAFE_MODE_VALASZ
    assert o.motion.calls == []


def test_ask_a_NYELVI_ort_is_atengedi(monkeypatch):
    """Angol válasz -> újrapróbálkozás „Magyarul válaszolj!"-jal, és az megy ki."""
    from freedroid.orchestrator import MAGYARUL

    class KetValasz(FakeLLM):
        def generate(self, prompt: str) -> str:
            self.promptok.append(prompt)
            return ("I am a robot and this is not Hungarian at all."
                    if len(self.promptok) == 1 else "Szabi vagyok, Teremtőm.")

    llm = KetValasz()
    o = kerdezo(llm, monkeypatch)
    assert o.ask("Who are you?") == "Szabi vagyok, Teremtőm."
    assert llm.promptok[1].startswith(MAGYARUL)


def test_start_bemelegiti_a_modellt(monkeypatch):
    """A hidegindítás 21 másodperc — az a csend nem eshet az első kérdésre."""
    llm = FakeLLM()
    o = kerdezo(llm, monkeypatch)
    o.start()
    assert llm.melegitve is True


def test_a_hianyzo_korpusz_nem_nemitja_el(monkeypatch):
    """Tények nélkül is tud beszélni — csak kevesebbet tud."""
    llm = FakeLLM("Szia, Teremtőm.")
    o = Orchestrator(motion=FakeMotion(), watchdog=FakeWatchdog(), llm=llm)
    monkeypatch.setattr("freedroid.orchestrator.transcript.log", lambda *a, **k: None)
    monkeypatch.setattr("freedroid.rag.corpus.load_corpus",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nincs korpusz")))
    assert o.ask("Mi az a Yotengrit?") == "Szia, Teremtőm."


def test_az_atirat_rogziti_a_MODELLT_es_az_INDOKOT(monkeypatch):
    """A `forras` csak annyit mond: „cloud". Az, hogy a v12-t vagy egy nyers
    bázismodellt kérdeztük, a MODELL mezőből derül ki."""
    naplo = []
    o = Orchestrator(motion=FakeMotion(), watchdog=FakeWatchdog(), llm=FakeLLM("Szia."))
    monkeypatch.setattr("freedroid.orchestrator.transcript.log",
                        lambda e, *a, **k: naplo.append(e))
    monkeypatch.setattr(o, "_talalatok", lambda k: [])
    o.ask("Ki vagy?")
    (e,) = naplo
    assert e.forras == "cloud"
    assert e.modell == "csaba_ajtony/szabi-8b-v12"
    assert e.hatter_indok == "cloud: felelt (csaba_ajtony/szabi-8b-v12)"


def test_a_MASODIK_generalas_bukasa_is_safe_mode(monkeypatch):
    """PR #86 review: a nyelvi őr MÁSODSZOR is hívja a modellt.

    Ha a háttér a két hívás között esik el, a `LLMUnavailable` az `ask()`-ból szállt
    volna ki, magával rántva a hurkot — épp azt az egy dolgot rontva el, amiért a safe
    mode létezik.
    """
    from freedroid.llm import LLMUnavailable
    from freedroid.orchestrator import SAFE_MODE_VALASZ

    class ElsoreAngolAztanHalott(FakeLLM):
        def generate(self, prompt: str) -> str:
            self.promptok.append(prompt)
            if len(self.promptok) == 1:
                return "I am a robot and this is not Hungarian at all."
            raise LLMUnavailable("cloud: nem elérhető; edge: nem elérhető")

    naplo = []
    llm = ElsoreAngolAztanHalott()
    o = Orchestrator(motion=FakeMotion(), watchdog=FakeWatchdog(), llm=llm)
    monkeypatch.setattr("freedroid.orchestrator.transcript.log",
                        lambda e, *a, **k: naplo.append(e))
    monkeypatch.setattr(o, "_talalatok", lambda k: [])

    assert o.ask("Who are you?") == SAFE_MODE_VALASZ
    assert len(llm.promptok) == 2          # tényleg a MÁSODIK hívás bukott el
    (e,) = naplo
    assert e.forras == "safe"
    # A nyers első választ a napló megőrzi — e nélkül pont a legérdekesebb kör veszne el.
    assert e.valasz.startswith("I am a robot")
