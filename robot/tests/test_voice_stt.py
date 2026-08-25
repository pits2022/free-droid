"""STT + VAD — ami mikrofon és whisper.cpp NÉLKÜL is elromolhat.

A felismerés minőségét csak a Pi-n lehet megítélni; itt az van, ami e nélkül is
eltörik: az energia-számítás, a VAD állapotgépe (elő-roll, csendszámlálás,
időkorlátok) és a whisper-parancs alakja.
"""

from __future__ import annotations

import array
import dataclasses
import math

import pytest

from freedroid.config.settings import Settings, VoiceSettings
from freedroid.voice import EnergyVAD, WhisperCppSTT, rms

RATE = 16000
DARAB_S = 0.05
MINTA_DARAB = int(RATE * DARAB_S)          # 800 minta = 1600 bájt


def pcm(amplitudo: int, darabok: int = 1) -> bytes:
    """`darabok` darab 50 ms-os blokk, adott amplitúdóval (négyszögjel)."""
    return array.array("h", [amplitudo] * (MINTA_DARAB * darabok)).tobytes()


def beallitas(**kw) -> Settings:
    return dataclasses.replace(Settings(), voice=VoiceSettings(**kw))


# --- energia -----------------------------------------------------------------------

def test_a_csend_nulla_a_jel_nem():
    assert rms(pcm(0)) == 0.0
    assert rms(pcm(1000)) == pytest.approx(1000.0)


def test_az_ures_bemenet_nem_hasal_el():
    """A felvétel legelején nulla bájt is jöhet — ne nullával osszunk."""
    assert rms(b"") == 0.0


def test_a_PARATLAN_bajt_nem_viszi_el_a_felvetelt():
    """Egy félbevágott folyam utolsó fél mintája miatt nem szabad elveszíteni a mondatot.

    (Az `array.frombytes` páratlan hosszra ValueError-t dob — ezért a csonkítás.)
    """
    assert rms(pcm(1000) + b"\x01") == pytest.approx(1000.0)


def test_az_audioop_hianyat_potoljuk():
    """A Pi Python 3.13-on fut, ahonnan az `audioop` KI LETT VÉVE (PEP 594).
    Az érték ugyanaz kell legyen, mint a kézzel számolt effektív érték."""
    minta = array.array("h", [100, -200, 300, -400])
    varhato = math.sqrt(sum(x * x for x in minta) / len(minta))
    assert rms(minta.tobytes()) == pytest.approx(varhato)


# --- VAD állapotgép ----------------------------------------------------------------

class AlFelvevo:
    """`arecord` helyett: előre megírt darabokat ad vissza, majd EOF-ot."""

    def __init__(self, darabok: list[bytes]):
        self._darabok = list(darabok)
        self.stdout = self
        self.stderr = _Ures()
        self.olvasasok = 0

    def read(self, n: int = -1) -> bytes:
        self.olvasasok += 1
        return self._darabok.pop(0) if self._darabok else b""

    def kill(self) -> None:
        return None

    def wait(self, timeout=None):
        return 0


class _Ures:
    def read(self, n: int = -1) -> bytes:
        return b""


def vad_futtat(darabok: list[bytes], monkeypatch, **kw) -> bytes:
    from freedroid import voice

    felvevo = AlFelvevo(darabok)
    monkeypatch.setattr(voice.subprocess, "Popen", lambda *a, **k: felvevo)
    return EnergyVAD(beallitas(**kw)).record_until_silence()


def test_a_kuszob_a_MERT_zajszinthez_igazodik(monkeypatch):
    """Egy fix küszöb a zajos teremben és a csendes szobában nem lehet ugyanaz — a
    demó pedig a zajos helyen lesz. Itt a zaj 400, tehát a 3x-os szorzóval 1200 a
    küszöb: az 500-as "beszéd" NEM indítaná el a felvételt, a 3000-es igen."""
    kalib = [pcm(400)] * 6          # 0,3 s zajszint-mérés
    halk = [pcm(500)] * 4           # a zaj fölött van, de a küszöb alatt
    hangos = [pcm(3000)] * 2
    csend = [pcm(0)] * 20
    felvett = vad_futtat(kalib + halk + hangos + csend, monkeypatch,
                         vad_min_rms=1.0, vad_snr=3.0)
    # A halk rész csak elő-rollként kerülhet be, a hangos mindenképp:
    assert len(felvett) > 0
    assert rms(felvett) > 500


def test_az_ELO_ROLL_megorzi_a_szo_elejet(monkeypatch):
    """A küszöböt már a szó KÖZEPÉN lépjük át, tehát elő-roll nélkül a mondat első
    hangja levágva menne a Whisperhez — egy levágott "Szabi" felismerhetetlen."""
    darabok = [pcm(10)] * 6 + [pcm(20)] * 6 + [pcm(5000)] * 2 + [pcm(0)] * 20
    kozos = dict(vad_min_rms=1000.0, vad_silence_s=0.25)
    vele = vad_futtat(darabok, monkeypatch, vad_preroll_s=0.3, **kozos)
    nelkule = vad_futtat(darabok, monkeypatch, vad_preroll_s=0.0, **kozos)
    # A teszt ÖNMAGÁT bizonyítja: a különbség pontosan a 0,3 s elő-roll (6 darab).
    assert len(vele) - len(nelkule) == 6 * MINTA_DARAB * 2


def test_a_csend_zarja_a_mondatot_nem_a_maximum(monkeypatch):
    kalib = [pcm(10)] * 6
    beszed = [pcm(5000)] * 4
    csend = [pcm(0)] * 40
    felvett = vad_futtat(kalib + beszed + csend, monkeypatch,
                         vad_min_rms=1000.0, vad_preroll_s=0.0,
                         vad_silence_s=0.25, vad_max_s=15.0)
    # 4 beszéd + 5 csend-darab (0,25 s), nem a teljes 40 csend-darab.
    assert len(felvett) < len(b"".join(beszed + csend))


def test_a_NEMA_mikrofon_ures_hangot_ad_nem_hibat(monkeypatch):
    """Ha senki nem szólal meg, az nem hiba: nincs mondat. Egy kivétel itt a
    `run()` hurkot állítaná meg minden csendes körben."""
    kalib = [pcm(10)] * 6
    assert vad_futtat(kalib + [pcm(10)] * 200, monkeypatch,
                      vad_min_rms=1000.0, vad_start_timeout_s=0.001) == b""


def test_a_megszakadt_felvetel_HANGOS(monkeypatch):
    """EOF a felvevőtől = a mikrofon eltűnt. Ez ELLENTÉTBEN a csenddel valódi hiba."""
    with pytest.raises(RuntimeError, match="megszakadt"):
        vad_futtat([], monkeypatch)


# --- whisper-parancs ---------------------------------------------------------------

def test_a_SZOTAR_PROMPT_bekerul_a_parancsba(tmp_path, monkeypatch):
    """MÉRVE 2026-08-25: prompt nélkül a "Yotengrit" -> "tenvrít". A robot
    legfontosabb fogalma. Ha a prompt kiesne a parancsból, a hiba NÉMA lenne:
    a felismerés csak rosszabb lenne, nem hibás."""
    from freedroid import voice

    modell = tmp_path / "m.bin"
    modell.write_bytes(b"x")
    parancsok: list[list[str]] = []

    class Kesz:
        returncode = 0
        stdout = b" Jo napot, Teremto.\n"
        stderr = b""

    monkeypatch.setattr(voice.subprocess, "run",
                        lambda p, **k: (parancsok.append(p), Kesz())[1])
    stt = WhisperCppSTT(beallitas(whisper_model=str(modell),
                                  stt_prompt="Szabi, Yotengrit."))
    assert stt.transcribe(pcm(1000)) == "Jo napot, Teremto."
    assert "--prompt" in parancsok[0]
    assert "Szabi, Yotengrit." in parancsok[0]
    # a `-f` és a fájl VÉGIG a parancs végén marad
    assert parancsok[0][-2] == "-f"


def test_ures_hangra_nem_indul_whisper(tmp_path, monkeypatch):
    from freedroid import voice

    def tilos(*a, **k):
        raise AssertionError("üres hangra nem szabad folyamatot indítani")
    monkeypatch.setattr(voice.subprocess, "run", tilos)
    assert WhisperCppSTT(beallitas()).transcribe(b"") == ""


def test_a_hianyzo_modell_HANGOS(tmp_path):
    stt = WhisperCppSTT(beallitas(whisper_model=str(tmp_path / "nincs.bin")))
    with pytest.raises(RuntimeError, match="nem található"):
        stt.transcribe(pcm(1000))


def test_a_BELELOGO_beszed_nem_fujja_fel_a_kuszobot(monkeypatch):
    """MÉRVE 2026-08-25, és ez tette használhatatlanná az első változatot.

    A zajszint-mérés a felvétel ELEJÉN van. Ha a beszélő azonnal megszólal (ENTER után
    azt teszi), ÁTLAGgal a küszöb a saját hangja háromszorosa lesz — a normál beszéd
    sosem lépi át, csak a kiabálás. MINIMUMmal a mérőablak legcsendesebb darabja számít.

    Itt a mérőablak fele csend (100), fele beszéd (5000):
      átlaggal:  (100+5000)/2 * 3 = 7650  -> a 3000-es beszédet NEM hallaná meg
      minimummal: 100 * 3        =  300  -> meghallja
    """
    kalib = [pcm(100)] * 3 + [pcm(5000)] * 3
    beszed = [pcm(3000)] * 2
    csend = [pcm(0)] * 20
    felvett = vad_futtat(kalib + beszed + csend, monkeypatch,
                         vad_min_rms=1.0, vad_snr=3.0, vad_preroll_s=0.0)
    assert felvett, "a normál hangerőt is meg kell hallania"
