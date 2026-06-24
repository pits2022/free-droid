"""Offline voice pipeline: wake word → STT → (LLM) → TTS, plus VAD.

All components run locally on the Pi (sovereignty requirement):
  - wake word: openWakeWord ("Szabi")
  - STT: whisper.cpp (Hungarian)
  - TTS: Piper (hu_HU-anonymous-medium, pitch-tuned younger)
  - VAD: detect end-of-speech
Interfaces + stubs only.
"""

from __future__ import annotations

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
    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.2: integrate Piper hu_HU-anonymous-medium")

    def speak(self, text: str) -> None:
        raise NotImplementedError
