"""Piper TTS — a hang-lánc azon része, ami hangkártya NÉLKÜL is mérhető.

A valódi lejátszást a Pi-n kell hallani; itt az van, ami e nélkül is elromolhat: a
mintavételi ráta forrása, a parancs alakja és az üres bemenet.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from freedroid.config.settings import Settings, VoiceSettings
from freedroid.voice import PiperTTS


def hang(tmp_path, synth=None, **kw) -> PiperTTS:
    """Piper-példány egy KÉSZ (de üres súlyú) modell-config mellett. A `synth` a
    cserélhető szintetizátor: szöveg -> PCM-darabok; nélküle a valódi modell töltődne."""
    (tmp_path / "v.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 16000}}))
    cfg = VoiceSettings(piper_model=str(tmp_path / "v"), **kw)
    return PiperTTS(dataclasses.replace(Settings(), voice=cfg), synth=synth)


def test_a_rata_a_MODELL_configjabol_jon(tmp_path):
    """Nem beégetett 22050: az a `medium` értéke, a low/high hangoké más. Rossz ráta
    nem hibát ad, hanem TORZ (gyorsított/lassított) beszédet — némán."""
    assert hang(tmp_path).sample_rate() == 16000


def test_hianyzo_config_HANGOS_es_megmondja_hogy_KET_fajl_kell(tmp_path):
    cfg = VoiceSettings(piper_model=str(tmp_path / "nincs_ilyen"))
    with pytest.raises(RuntimeError, match="KÉT"):
        PiperTTS(dataclasses.replace(Settings(), voice=cfg)).sample_rate()


def test_ures_szoveg_nem_indit_folyamatot(tmp_path, monkeypatch):
    """Nem hiba, csak nincs mit mondani — de folyamatot se indítsunk rá."""
    from freedroid import voice

    def tilos(*a, **k):
        raise AssertionError("nem indulhat folyamat üres szövegre")
    monkeypatch.setattr(voice.subprocess, "Popen", tilos)
    hang(tmp_path).speak("   \n  ")


def test_a_lejatszo_parancsba_a_MERT_rata_kerul(tmp_path, monkeypatch):
    """A `--output-raw` fejléc NÉLKÜLI PCM-et ad, tehát a lejátszónak meg kell mondani
    a formátumot. Ha a ráta nem a modellből jön, a hang torz lesz — némán."""
    from freedroid import voice

    parancsok: list[list[str]] = []

    class AlFolyamat:
        returncode = 0

        def __init__(self, parancs, **kw):
            parancsok.append(parancs)
            self.stdin = _Nyelo()
            self.stdout = _Nyelo()
            self.stderr = _Nyelo()

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(voice.subprocess, "Popen", AlFolyamat)
    hang(tmp_path, synth=lambda t: [b"\0" * 4]).speak("Megyek, Teremtőm.")

    # EGYETLEN folyamat: a lejátszó. A piper 2026-09-03 óta a folyamaton BELÜL fut
    # (a modell egyszer töltődik, mérve 2,07 s hívásonként a binárissal).
    (jatszo,) = parancsok
    assert "16000" in jatszo, jatszo


class _Nyelo:
    def write(self, _b): return None
    def close(self): return None
    def read(self): return b""


def test_a_binaris_kereses_a_VENV_bol_indul(tmp_path, monkeypatch):
    """Egyetlen szabály szolgálja ki a health-checket és a tényleges hívást.

    Enélkül előfordulhatna, hogy az egészség-ellenőrzés MEGTALÁLJA a Pipert, a beszéd
    pedig nem — és pont a szolgáltatásként futó roboton, ahol senki nem nézi.
    """
    import sys

    from freedroid.voice import find_voice_binary

    alvenv = tmp_path / "bin"
    alvenv.mkdir()
    (alvenv / "piper").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(alvenv / "python"))
    assert find_voice_binary("piper") == str(alvenv / "piper")

    # ami nincs se a venv-ben, se a PATH-on -> None (nem üres string, nem kivétel)
    assert find_voice_binary("nincs-ilyen-binaris-remelem") is None


def test_a_beragadt_lejatszo_IDOKORLATRA_bukik_nem_nemul_el(tmp_path):
    """PR #91 review: ha a lejátszó beragad a hangeszköz megnyitásán anélkül, hogy
    kilépne, a robot NÉMÁN, határidő nélkül állna meg — a legrosszabb kimenet."""
    import time

    tts = hang(tmp_path, synth=lambda t: [b"\0" * 100], play_command="sleep 30",
               speak_timeout_s=1.0)
    kezd = time.perf_counter()
    with pytest.raises(RuntimeError, match="beragadt"):
        tts.speak("Megyek, Teremtőm.")
    # És tényleg az IDŐKORLÁT vetett véget neki, nem valami más hiba.
    assert 0.5 < time.perf_counter() - kezd < 15


def test_a_szintezis_hibaja_a_SAJAT_uzenetet_mondja(tmp_path):
    """Rossz modellnél a szintézis dob. A hívónak az ŐZENETÉT kell látnia, nem egy
    nyers csőhibát vagy egy néma, üres lejátszást."""
    def rossz(t):
        raise RuntimeError("nincs ilyen modell")
        yield  # noqa: RET503 — generátor kell

    tts = hang(tmp_path, synth=rossz, play_command="cat > /dev/null")
    with pytest.raises(RuntimeError, match="nincs ilyen modell"):
        tts.speak("Megyek, Teremtőm.")


def test_az_idokorlat_a_TELJES_beszedre_vonatkozik(tmp_path):
    """PR #91 review: két külön időkorlát a legrosszabb esetben a KÉTSZERESÉT engedné.
    Itt a szintézis 0,8 s, a lejátszó beragad; közös korláttal ~1 s, külön ~1,8 s."""
    import time

    def lassu(t):
        time.sleep(0.8)
        yield b"\0" * 100

    tts = hang(tmp_path, synth=lassu, play_command="sleep 30", speak_timeout_s=1.0)
    kezd = time.perf_counter()
    with pytest.raises(RuntimeError, match="beragadt"):
        tts.speak("Megyek, Teremtőm.")
    assert time.perf_counter() - kezd < 1.5


def test_warm_up_EGYSZER_tolt_es_a_hibaja_az_utvonalat_mondja(tmp_path, monkeypatch):
    """A modell hívásonkénti újratöltése volt a 2 s-os „lemaradás" (mérve 2026-09-03)."""
    import sys
    import types

    toltesek = []

    class AlVoice:
        @staticmethod
        def load(path):
            toltesek.append(path)
            return object()
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=AlVoice))
    tts = hang(tmp_path)
    tts.warm_up()
    tts.warm_up()
    assert toltesek == [str(tmp_path / "v") + ".onnx"]      # egyszer, KITERJESZTÉSSEL

    class Rossz:
        @staticmethod
        def load(path):
            raise FileNotFoundError(path)
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=Rossz))
    with pytest.raises(RuntimeError, match="nem tölthető be .*v.onnx"):
        hang(tmp_path).warm_up()


def test_csipogas_a_lejatszora_megy_es_nullaval_kikapcsol(monkeypatch):
    from freedroid import voice

    hivasok = []
    monkeypatch.setattr(voice.subprocess, "run",
                        lambda cmd, **kw: hivasok.append((cmd, len(kw["input"]))))
    voice.csipog("aplay -q -r {rate} -f S16_LE -t raw -", rate=22050, seconds=0.12)
    (cmd, n), = hivasok
    assert "22050" in cmd and n == int(22050 * 0.12) * 2       # 16 bites mono
    voice.csipog("aplay -r {rate}", seconds=0)
    assert len(hivasok) == 1                                    # 0 = nincs hang
