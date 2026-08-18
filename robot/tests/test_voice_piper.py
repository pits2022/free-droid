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


def hang(tmp_path, **kw) -> PiperTTS:
    """Piper-példány egy KÉSZ (de üres súlyú) modell-config mellett."""
    (tmp_path / "v.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 16000}}))
    cfg = VoiceSettings(piper_model=str(tmp_path / "v"), **kw)
    return PiperTTS(dataclasses.replace(Settings(), voice=cfg))


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

        def wait(self):
            return 0

    monkeypatch.setattr(voice.subprocess, "Popen", AlFolyamat)
    hang(tmp_path).speak("Megyek, Teremtőm.")

    gen, jatszo = parancsok
    # A bináris TELJES útvonallal megy: a `.venv/bin` nincs a PATH-on, amikor a systemd
    # a `{venv}/bin/freedroid`-ot indítja — `uv run` alatt viszont igen, tehát ez a hiba
    # pont a fejlesztés közben LÁTHATATLAN, és először a szolgáltatásként futó roboton
    # jönne elő.
    assert gen[0].endswith("piper") and "--output-raw" in gen
    assert gen[gen.index("--model") + 1].endswith(".onnx")   # a KITERJESZTÉS is kell
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
