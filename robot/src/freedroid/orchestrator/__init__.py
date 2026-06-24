"""Main async loop: wake → STT → LLM → TTS, with parallel tool execution.

Ties together voice, llm, tools, motion and the safety watchdog. The watchdog runs
independently; safe mode disables motion and uses canned replies on a critical fault.
Skeleton only — no implementation.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freedroid.config.settings import Settings


class State(str, Enum):
    LISTENING = "listening"   # waiting for wake word
    THINKING = "thinking"     # STT + LLM
    SPEAKING = "speaking"     # TTS + tool execution
    SAFE_MODE = "safe_mode"   # critical fault: motion disabled, canned replies


class Orchestrator:
    """Top-level coordinator. STUB.

    Wiring order (see robot/README.md): config → motion + safety → tools → llm → voice.
    The safety watchdog is started before any motion is ever possible.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.3: wire modules and implement the loop")

    async def run(self) -> None:
        # Intended shape (not yet implemented):
        #   self.watchdog.start()
        #   while True:
        #       await wake → record → transcribe → llm.generate
        #       speak(reply) ∥ dispatch(parse_tools(reply))
        raise NotImplementedError


def main() -> None:
    """Console entry point (`freedroid`). STUB."""
    asyncio.run(Orchestrator().run())
