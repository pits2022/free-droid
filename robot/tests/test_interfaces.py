"""Interface-shape guards: the concrete controllers expose the methods the
orchestrator/tools layer will call. These stay valid after Phase 4 implements them.
"""

from __future__ import annotations

import pytest

from freedroid.camera import PanTiltCamera
from freedroid.llm import FallbackLLMClient
from freedroid.motion import CytronMotionController
from freedroid.orchestrator import Orchestrator
from freedroid.safety import UltrasonicWatchdog
from freedroid.tools.handlers import ToolRegistry
from freedroid.voice import OpenWakeWord, PiperTTS, WhisperCppSTT

EXPECTED = [
    (CytronMotionController, ["move", "turn", "stop", "set_speed"]),
    (PanTiltCamera, ["pan", "tilt", "action"]),
    (UltrasonicWatchdog, ["start", "stop_monitoring", "distances_cm", "is_blocked"]),
    (FallbackLLMClient, ["generate", "active_backend"]),
    (OpenWakeWord, ["wait_for_wake"]),
    (WhisperCppSTT, ["transcribe"]),
    (PiperTTS, ["speak"]),
    (ToolRegistry, ["register", "dispatch"]),
    (Orchestrator, ["run"]),
]


@pytest.mark.parametrize("cls,methods", EXPECTED, ids=[c.__name__ for c, _ in EXPECTED])
def test_class_exposes_expected_methods(cls, methods):
    for m in methods:
        assert callable(getattr(cls, m, None)), f"{cls.__name__} missing {m}()"
