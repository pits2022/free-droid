"""LLM client with cloud→edge fallback.

Cloud (Ollama over WireGuard) is preferred when reachable; otherwise the local edge
Ollama serves the same fine-tuned model offline. On a hard failure the orchestrator
drops to safe mode (handled there, not here).
Interface + stub only.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from freedroid.config.settings import Settings


class Backend(str, Enum):
    CLOUD = "cloud"
    EDGE = "edge"


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...
    def active_backend(self) -> Backend: ...


class FallbackLLMClient:
    """Tries cloud first, falls back to edge. STUB."""

    def __init__(self, settings: Settings | None = None) -> None:
        raise NotImplementedError("Phase 4.2: implement cloud→edge Ollama fallback")

    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    def active_backend(self) -> Backend:
        raise NotImplementedError
