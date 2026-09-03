"""A `run()` hurok: a trigger, a megszakítás és a hibatűrés.

Amit itt mérünk, az nem a hang minősége (az a Pi-n hallható) — hanem a három dolog,
ami a hurokban NÉMÁN romolhat el:

  1. egy gombnyomás egy TELJES kört visz végig (felvétel -> STT -> ask -> beszéd);
  2. az ALLJ AZONNAL hat, nem a kör végén — beszéd KÖZBEN is;
  3. egy hibás kör nem viszi el a hurkot.

A 2. a legfontosabb: pont az a tulajdonság, amiért a megszakítás a trigger SZÁLÁN
történik, és nem a hurok következő fordulójában.
"""

from __future__ import annotations

import queue
import threading

import pytest

from freedroid.orchestrator import SAFE_MODE_VALASZ, Orchestrator
from freedroid.voice.trigger import BillentyuTrigger, Esemeny, TriggerBusz


class HamisVAD:
    def __init__(self) -> None:
        self.hivasok = 0

    def record_until_silence(self) -> bytes:
        self.hivasok += 1
        return b"\x00\x01" * 100


class HamisSTT:
    def __init__(self, szoveg: str = "Ki vagy te?") -> None:
        self._szoveg = szoveg

    def transcribe(self, audio: bytes) -> str:
        return self._szoveg


class HamisTTS:
    """Beszéd helyett feljegyzés — és megszakíthatóan, mint a Piper."""

    def __init__(self) -> None:
        self.mondatok: list[str] = []
        self.megszakitva = threading.Event()
        self.beszel = threading.Event()
        self.engedd = threading.Event()

    def speak(self, text: str) -> None:
        self.mondatok.append(text)
        self.beszel.set()
        self.engedd.wait(timeout=2.0)   # "hosszú" mondat, hogy megszakítható legyen

    def abort(self) -> None:
        self.megszakitva.set()
        self.engedd.set()


class HamisMotion:
    def __init__(self) -> None:
        self.megallitva = 0
        self.heading = None
        self.is_turning = False

    def stop(self) -> None:
        self.megallitva += 1

    def close(self) -> None:
        pass


class HamisWatchdog:
    fault = None

    def start(self) -> None:
        pass

    def stop_monitoring(self) -> None:
        pass


def robot(**kw) -> Orchestrator:
    """Orchestrátor VALÓDI hardver és hálózat nélkül."""
    return Orchestrator(motion=HamisMotion(), watchdog=HamisWatchdog(),
                        llm=object(), **kw)


# ── 1. a trigger-forrás ──────────────────────────────────────────────────────────

class HamisFolyam:
    """`readline()`-t adó folyam, hogy a billentyű-forrás stdin nélkül próbálható."""

    def __init__(self, sorok: list[str]) -> None:
        self._sorok = list(sorok)
        self.kesz = threading.Event()

    def readline(self) -> str:
        if not self._sorok:
            self.kesz.set()
            return ""       # EOF
        return self._sorok.pop(0)


@pytest.mark.parametrize(("bemenet", "vart"), [
    ("\n", Esemeny.FIGYELJ),
    ("  \n", Esemeny.FIGYELJ),
    ("s\n", Esemeny.ALLJ),
    ("S\n", Esemeny.ALLJ),
    ("stop\n", Esemeny.ALLJ),
])
def test_a_billentyu_forras_a_VART_esemenyt_kuldi(bemenet, vart):
    sor: queue.Queue = queue.Queue()
    BillentyuTrigger(HamisFolyam([bemenet])).start(sor)
    assert sor.get(timeout=2.0) is vart


def test_az_ALLJ_AZONNAL_lefuttatja_a_mellekhatast_nem_a_sorbol():
    """A busz szerződése: az `azonnal` a FORRÁS szálán fut, még mielőtt bárki kiolvasná
    a sort. Enélkül az egész terv értelmét vesztené — a főszál épp beszél."""
    futott = threading.Event()
    busz = TriggerBusz(BillentyuTrigger(HamisFolyam(["s\n"])), azonnal=futott.set)
    busz.start()
    assert futott.wait(timeout=2.0), "az ALLJ mellékhatása nem futott le"
    assert busz.allj.is_set()
    busz.close()


def test_egy_elhasalo_mellekhatas_nem_oli_meg_a_tovabbito_szalat():
    """Ha a motor-leállítás dob, a TÖBBI gombnyomásnak akkor is meg kell érkeznie —
    különben egy hiba után a robot süket a gombra."""
    def robban() -> None:
        raise RuntimeError("a motor nem áll le")

    busz = TriggerBusz(BillentyuTrigger(HamisFolyam(["s\n", "\n"])), azonnal=robban)
    busz.start()
    assert busz.var(timeout=2.0) is Esemeny.ALLJ
    assert busz.var(timeout=2.0) is Esemeny.FIGYELJ
    busz.close()


# ── 2. egy teljes kör ────────────────────────────────────────────────────────────

def test_egy_kor_vegigmegy_a_lancon(monkeypatch):
    vad, stt, tts = HamisVAD(), HamisSTT("Ki vagy te?"), HamisTTS()
    tts.engedd.set()                       # ne blokkoljon
    o = robot(stt=stt, tts=tts, vad=vad)
    monkeypatch.setattr(o, "ask", lambda k: f"válasz: {k}")
    busz = TriggerBusz()

    o._egy_kor(stt, tts, vad, busz)

    assert vad.hivasok == 1
    assert tts.mondatok == ["válasz: Ki vagy te?"]


def test_ures_atirat_eseten_NEM_kerdezunk_es_NEM_beszelunk(monkeypatch):
    """Egy félrenyomott gomb ne szüljön LLM-hívást és egy találomra mondott mondatot."""
    vad, stt, tts = HamisVAD(), HamisSTT("   "), HamisTTS()
    tts.engedd.set()
    o = robot(stt=stt, tts=tts, vad=vad)
    kerdezett = []
    monkeypatch.setattr(o, "ask", lambda k: kerdezett.append(k) or "x")

    o._egy_kor(stt, tts, vad, TriggerBusz())

    assert kerdezett == []
    assert tts.mondatok == []


# ── 3. megszakítás ───────────────────────────────────────────────────────────────

def test_az_ALLJ_BESZED_KOZBEN_megszakit(monkeypatch):
    """A tét: a `speak()` blokkol, tehát a megszakításnak MÁS SZÁLRÓL kell jönnie.
    Ha ez elromlik, a vészstop csak mondathatáron hat — azaz gyakorlatilag sehogy."""
    vad, stt, tts = HamisVAD(), HamisSTT(), HamisTTS()
    o = robot(stt=stt, tts=tts, vad=vad)
    monkeypatch.setattr(o, "ask", lambda k: "egy nagyon hosszú monológ")

    busz = TriggerBusz(azonnal=o._azonnali_allj)
    szal = threading.Thread(target=o._egy_kor, args=(stt, tts, vad, busz), daemon=True)
    szal.start()
    assert tts.beszel.wait(timeout=2.0), "a beszéd el sem indult"

    o._azonnali_allj()                     # a "gombnyomás"
    szal.join(timeout=2.0)

    assert not szal.is_alive(), "a kör beragadt a megszakítás után"
    assert tts.megszakitva.is_set()
    assert o.motion.megallitva == 1, "az ALLJ nem állította meg a motorokat"


@pytest.mark.parametrize("mikor", ["felvetel_alatt", "gondolkodas_alatt"])
def test_az_ALLJ_a_beszed_ELOTT_eldobja_a_kort(monkeypatch, mikor):
    """MINDKÉT szakaszhatárt külön mérjük, és ez nem bőbeszédűség: az első változat
    csak a felvétel utáni őrt állította be, és egy MUTÁCIÓ (a beszéd előtti őr
    törlése) ÉSZREVÉTLENÜL ment át rajta — az első őr elfedte a másodikat.

    A `gondolkodas_alatt` a valódi eset: a gomb akkor megy le, amikor a modell épp
    válaszol (a felhős kör 0,4 s, az edge-es több másodperc — bőven van idő rá)."""
    vad, stt, tts = HamisVAD(), HamisSTT(), HamisTTS()
    tts.engedd.set()
    o = robot(stt=stt, tts=tts, vad=vad)
    busz = TriggerBusz()

    if mikor == "felvetel_alatt":
        busz.allj.set()
        monkeypatch.setattr(o, "ask", lambda k: "válasz")
    else:
        monkeypatch.setattr(o, "ask", lambda k: busz.allj.set() or "válasz")

    o._egy_kor(stt, tts, vad, busz)

    assert tts.mondatok == [], "megszakított kör után is megszólalt"


# ── 4. hibatűrés ─────────────────────────────────────────────────────────────────

def test_egy_hibas_kor_NEM_oli_meg_a_hurkot_hanem_megszolal(monkeypatch):
    """A néma, kilépett folyamat a színpadon visszahozhatatlan; egy rossz válasz nem."""
    class RobbanoSTT:
        def transcribe(self, audio: bytes) -> str:
            raise RuntimeError("a felhő és az edge is halott")

    tts = HamisTTS()
    tts.engedd.set()
    vad = HamisVAD()
    o = robot(stt=RobbanoSTT(), tts=tts, vad=vad)

    o._egy_kor(RobbanoSTT(), tts, vad, TriggerBusz())     # NEM dob

    assert tts.mondatok == [SAFE_MODE_VALASZ]


def test_egy_elhasalo_BESZED_sem_oli_meg_a_kort(monkeypatch):
    class NemaTTS:
        def speak(self, text: str) -> None:
            raise RuntimeError("foglalt hangeszköz")

    vad, stt = HamisVAD(), HamisSTT()
    o = robot(stt=stt, tts=NemaTTS(), vad=vad)
    monkeypatch.setattr(o, "ask", lambda k: "válasz")

    o._egy_kor(stt, NemaTTS(), vad, TriggerBusz())        # NEM dob


# ── 5. maga a run() huzalozás ────────────────────────────────────────────────────

def test_a_run_hurok_ALLJ_ra_nem_indit_kort_FIGYELJ_re_igen(monkeypatch):
    """A `_egy_kor` tesztjei a hurkot MAGÁT nem érintik: az `asyncio.to_thread`-es
    huzalozást, a FIGYELJ-szűrést és a `finally`-t csak ez méri. A forrás egy `s` (ALLJ)
    és egy üres sor (FIGYELJ), utána EOF — a hurok pontosan EGY kört futtat, aztán a
    lezárás után kilép."""
    import asyncio

    vad, stt, tts = HamisVAD(), HamisSTT(), HamisTTS()
    tts.engedd.set()
    o = robot(stt=stt, tts=tts, vad=vad)
    monkeypatch.setattr(o, "ask", lambda k: "válasz")

    busz = TriggerBusz(BillentyuTrigger(HamisFolyam(["s\n", "\n"])),
                       azonnal=o._azonnali_allj)
    o._trigger = busz

    async def hajt():
        # A hurok szándékosan VÉGTELEN (a robot nem áll le magától) — a teszt onnan
        # tudja, hogy kész, hogy a kör lefutott, és akkor mondja fel neki.
        feladat = asyncio.create_task(o.run())
        for _ in range(200):
            if tts.mondatok:
                break
            await asyncio.sleep(0.01)
        feladat.cancel()
        with pytest.raises(asyncio.CancelledError):
            await feladat

    asyncio.run(hajt())

    assert tts.mondatok == ["válasz"], "pontosan egy kör kellett volna, a FIGYELJ-re"
    assert vad.hivasok == 1, "az ALLJ nem indíthat felvételt"
    assert o.motion.megallitva == 1, "az ALLJ nem állította meg a motorokat"


# ── 6. leállás szolgáltatásként ──────────────────────────────────────────────────

def test_a_SIGTERM_lezarja_a_hardvert_nem_oli_meg_nyersen():
    """🔴 A Python alapértelmezett SIGTERM-kezelése AZONNALI kilépés: nem dob kivételt,
    tehát a `run()` `finally`-ja — ami a watchdogot és a motorvezérlőt lezárja — NEM
    futna le. Egy systemd-szolgáltatásnál ez járó lánctalpakat hagyna egy kilépett
    folyamat után, és pont a `systemctl stop` az az út, amin ez bekövetkezne.

    Külön folyamatban mérjük, mert a jelkezelő process-szintű állapot: ugyanabban a
    folyamatban beállítva átszivárogna a többi tesztre.
    """
    import subprocess
    import sys
    import textwrap

    program = textwrap.dedent('''
        import os, signal, sys
        sys.argv = ["freedroid"]
        import freedroid.orchestrator as o

        # A hurok helyett egy jelre váró csonk: azt mérjük, hogy a SIGTERM
        # KeyboardInterrupt-ot ad-e, nem azt, hogy a hurok mit csinál.
        def hamis_run(self):
            os.kill(os.getpid(), signal.SIGTERM)
            raise AssertionError("a SIGTERM nem szakította meg")

        o.Orchestrator.run = hamis_run
        o.Orchestrator.__init__ = lambda self, *a, **k: None
        o.main()
        print("LEZART_RENDESEN")
    ''')
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)

    assert "LEZART_RENDESEN" in r.stdout, (
        f"a SIGTERM nem KeyboardInterruptként érkezett — a lezárás elmaradna.\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr[-500:]!r}")


# ── 7. FIFO-trigger (a SZOLGÁLTATÁS útja) ────────────────────────────────────────

def test_a_fifo_trigger_esemenyt_ad_es_TOBB_jelzest_sem_von_ossze(tmp_path):
    """Ez az egyetlen út, amin a systemd alatt futó robot megszólítható (nincs stdin).

    A második állítás a lényegi: két gyors `echo` UGYANABBAN az olvasásban érkezhet, és
    ha a forrás a darabot egyben dolgozná fel, a második jelzés — akár egy ÁLLJ —
    elveszne."""
    from freedroid.voice.trigger import FifoTrigger

    ut = tmp_path / "trigger"
    sor: queue.Queue = queue.Queue()
    forras = FifoTrigger(ut)
    forras.start(sor)
    try:
        with open(ut, "w") as f:
            f.write("\n")          # FIGYELJ
            f.write("s\n")         # ÁLLJ, ugyanabban az írásban
            f.flush()
        assert sor.get(timeout=2.0) is Esemeny.FIGYELJ
        assert sor.get(timeout=2.0) is Esemeny.ALLJ
    finally:
        forras.close()


def test_a_fifo_TOBB_egymas_utani_jelzest_is_atenged(tmp_path):
    """`O_RDWR` nélkül a `read()` EOF-ot adna az első `echo` után, és a forrás elhallgatna
    — a robot pontosan EGYSZER lenne megszólítható, aztán süket maradna."""
    from freedroid.voice.trigger import FifoTrigger

    ut = tmp_path / "trigger"
    sor: queue.Queue = queue.Queue()
    forras = FifoTrigger(ut)
    forras.start(sor)
    try:
        for _ in range(3):
            with open(ut, "w") as f:      # KÜLÖN nyitás/zárás, mint egy `echo`
                f.write("\n")
            assert sor.get(timeout=2.0) is Esemeny.FIGYELJ
    finally:
        forras.close()


def test_a_ket_forras_UGYANAZT_a_nyelvtant_hasznalja():
    """Ha az `s` a FIFO-ban mást jelentene, mint a billentyűzeten, az a legrosszabb fajta
    meglepetés lenne — a STOP-é."""
    from freedroid.voice.trigger import _esemeny

    for szoveg in ("s", "S\n", " stop \n", "seg"):
        assert _esemeny(szoveg) is Esemeny.ALLJ, szoveg
    for szoveg in ("", "\n", "  \n", "figyelj"):
        assert _esemeny(szoveg) is Esemeny.FIGYELJ, szoveg


def test_a_fifo_lezarasa_NEM_dob_a_szalban(tmp_path):
    """`close()` MÁS SZÁLON fut, mint az olvasó ciklus. Ha a leírót közvetlenül a
    `self._fd`-ből olvasnánk, a `close()` beékelődhet, és az `os.read(None, ...)`
    `TypeError`-t dob — amit az `except OSError` NEM fog el, tehát a leállás egy
    elkapatlan veremkiíratással végződne egy daemon szálban. (PR #100 review, 2. kör.)

    A verseny szűk, ezért nem próbáljuk kikényszeríteni: közvetlenül azt mérjük, hogy a
    ciklus `None` leíró mellett RENDESEN kilép, nem dob."""
    import threading

    from freedroid.voice.trigger import FifoTrigger

    forras = FifoTrigger(tmp_path / "trigger")
    forras._fd = None                      # pontosan az az állapot, amit a close() hagy
    hiba: list[BaseException] = []

    def fut():
        try:
            forras._olvas(queue.Queue())
        except BaseException as e:          # noqa: BLE001 — épp a kivételt mérjük
            hiba.append(e)

    szal = threading.Thread(target=fut, daemon=True)
    szal.start()
    szal.join(timeout=2.0)

    assert not szal.is_alive(), "az olvasó ciklus beragadt lezárt leíró mellett"
    assert not hiba, f"a lezárás kivételt dobott a szálban: {hiba}"


# ── 5. előbb mond, aztán mozdul ─────────────────────────────────────────────────

def test_a_mozgas_a_beszed_UTAN_jon_es_az_allj_meg_is_akadalyozza(monkeypatch):
    """A Teremtő (2026-09-03): „előbb mondja, hogy balra fordulok, aztán forduljon".
    A lekérdező tool (scan_wifi) NEM halasztható: az eredménye maga a mondat."""
    from freedroid.orchestrator.guard import guard

    sorrend: list[str] = []

    class NaploTTS(HamisTTS):
        def speak(self, text: str) -> None:
            sorrend.append("beszéd")
            self.mondatok.append(text)

    class NaploTools:
        def dispatch(self, tool):
            sorrend.append(tool.name)
            return [] if tool.name == "scan_wifi" else None

    vad, stt, tts = HamisVAD(), HamisSTT("Fordulj balra!"), NaploTTS()
    o = robot(stt=stt, tts=tts, vad=vad)
    o.tools = NaploTools()
    monkeypatch.setattr(o, "ask", lambda k: o.execute_guarded(
        guard("Balra fordulok, Teremtőm. <tool>scan_wifi</tool><tool>turn left 90</tool>")))
    o._egy_kor(stt, tts, vad, TriggerBusz())
    assert sorrend == ["scan_wifi", "beszéd", "turn"]
    assert o._halasztott is None                       # a kör után nem marad függő köteg

    # ÁLLJ a beszéd alatt: a bejelentett fordulás EL SEM INDUL.
    sorrend.clear()
    busz = TriggerBusz()

    class AlljTTS(NaploTTS):
        def speak(self, text: str) -> None:
            super().speak(text)
            busz.allj.set()
    tts2 = AlljTTS()
    o._egy_kor(stt, tts2, vad, busz)
    assert sorrend == ["scan_wifi", "beszéd"]

    # Az `ask()` SZÖVEGES útja (halasztás nélkül) változatlan: azonnal mozdul.
    sorrend.clear()
    o.execute_guarded(guard("<tool>turn left 90</tool>"))
    assert sorrend == ["turn"]
