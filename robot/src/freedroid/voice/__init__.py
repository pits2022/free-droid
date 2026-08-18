"""Offline voice pipeline: wake word → STT → (LLM) → TTS, plus VAD.

All components run locally on the Pi (sovereignty requirement):
  - wake word: openWakeWord ("Szabi")
  - STT: whisper.cpp (Hungarian)
  - TTS: Piper (hu_HU-anonymous-medium, pitch-tuned younger)
  - VAD: detect end-of-speech
Interfaces + stubs only.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from freedroid.config.settings import Settings


class WakeWord(Protocol):
    def wait_for_wake(self) -> None:
        """Block until the 'Szabi' wake word is detected."""
        ...


class STT(Protocol):
    def transcribe(self, audio: bytes) -> str: ...


class TTS(Protocol):
    def speak(self, text: str) -> None: ...


class VAD(Protocol):
    def record_until_silence(self) -> bytes:
        """Record from the USB mic until the speaker stops."""
        ...


class OpenWakeWord:
    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.2: train + integrate 'Szabi' wake word")

    def wait_for_wake(self) -> None:
        raise NotImplementedError


class WhisperCppSTT:
    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.2: integrate whisper.cpp (Hungarian)")

    def transcribe(self, audio: bytes) -> str:
        raise NotImplementedError


class PiperTTS:
    """Piper TTS: szöveg -> nyers audio -> lejátszás. Offline, a Pi-n (szuverenitás).

    A `piper` BINÁRIST hívjuk, nem a Python API-t: a health-check is a binárist keresi
    (`which piper`), tehát egy út marad ellenőrizve.

    A két folyamat CSŐVEL van összekötve (`--output-raw | aplay`), nem ideiglenes
    WAV-fájlon át. Ez nem teljesítmény-kérdés: a demó előtti posztúra szerint a gépen
    NEM tárolunk elhangzott mondatot, egy `/tmp`-be írt hangfájl pedig pontosan az lenne.

    A kapcsolók MÉRVE, nem a dokumentációból: `piper --help` + három valódi futtatás
    (2026-08-18). A `--output-raw` 16 bites, mono, a modell mintavételi frekvenciáján —
    ezért kell a rátát a modell mellől kiolvasni, és nem beégetni.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        from freedroid.config.settings import load_settings

        self._cfg = (settings or load_settings()).voice
        # `expanduser`: a config `~`-t ír (a modell a robot-user home-jában van), és a
        # subprocess NEM oldja fel a tildét — shell nélkül futunk, nincs, ami kibontsa.
        self._model = str(Path(self._cfg.piper_model).expanduser())

    def sample_rate(self) -> int:
        """A modell mintavételi frekvenciája, a MELLETTE lévő configból.

        Nem beégetett 22050: az a `medium` szint értéke, a `low`/`high` hangoké más.
        Egy rossz ráta nem hibát ad, hanem TORZ, gyorsított vagy lassított beszédet —
        némán. Ezért olvassuk ki.
        """
        config = Path(self._model + ".onnx.json")
        try:
            return int(json.loads(config.read_text(encoding="utf-8"))["audio"]["sample_rate"])
        except (OSError, KeyError, ValueError) as e:
            raise RuntimeError(
                f"a Piper hang configja nem olvasható ({config}): {e} — a hang KÉT "
                f"fájlból áll (.onnx + .onnx.json), és mindkettő kell") from e

    def speak(self, text: str) -> None:
        """Kimondja a szöveget. Üres szövegre nem csinál semmit (nem hiba).

        Hiba esetén `RuntimeError` — a hívó (orchestrátor) dönti el, elnyeli-e. Egy néma
        `except: pass` itt azt jelentené, hogy a robot a színpadon csendben marad, és
        semmi nem árulja el, miért.
        """
        if not (text := text.strip()):
            return

        gen_parancs = ["piper", "--model", self._model + ".onnx", "--output-raw",
                       "--length-scale", str(self._cfg.length_scale)]
        jatszo_parancs = shlex.split(self._cfg.play_command.format(rate=self.sample_rate()))

        try:
            gen = subprocess.Popen(gen_parancs, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise RuntimeError(f"a `piper` nem indult el: {e}") from e
        try:
            jatszo = subprocess.Popen(jatszo_parancs, stdin=gen.stdout,
                                      stderr=subprocess.PIPE)
        except OSError as e:
            gen.kill()
            gen.wait()
            raise RuntimeError(f"a lejátszó nem indult el ({jatszo_parancs[0]}): {e}") from e

        # A SZÜLŐNEK el kell engednie a cső olvasó végét, különben az `aplay` sosem lát
        # EOF-ot, és a beszéd végén örökre várna. Ez a klasszikus cső-holtpont.
        gen.stdout.close()

        gen.stdin.write(text.encode("utf-8"))
        gen.stdin.close()
        gen_hiba = gen.stderr.read().decode("utf-8", "replace")
        gen.wait()
        jatszo_hiba = jatszo.stderr.read().decode("utf-8", "replace")
        jatszo.wait()

        if gen.returncode:
            raise RuntimeError(f"piper hiba ({gen.returncode}): {gen_hiba.strip()[:300]}")
        if jatszo.returncode:
            raise RuntimeError(f"lejátszás hiba ({jatszo.returncode}): "
                               f"{jatszo_hiba.strip()[:300]}")
