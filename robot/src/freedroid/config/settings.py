"""Runtime tunables with sane defaults. Override via env / config file later.

Defaults are validated once at construction (range checks) so an out-of-range
value fails loudly at startup rather than mis-driving a motor silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class LLMEndpoints:
    # Cloud Ollama is reachable over WireGuard; edge Ollama is loopback-only.
    cloud_url: str = "http://10.0.0.1:11434"
    edge_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:3b"  # placeholder — final = fine-tuned GGUF Modelfile tag
    cloud_timeout_s: float = 8.0


@dataclass(frozen=True)
class SafetySettings:
    stop_threshold_cm: float = 25.0   # confirmed with Creator
    poll_interval_s: float = 0.05     # watchdog thread cadence
    # Per-sensor overrides, e.g. {"front": 30.0}. Read-only (frozen settings).
    per_sensor_cm: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.stop_threshold_cm <= 0:
            raise ValueError("stop_threshold_cm must be > 0")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")


@dataclass(frozen=True)
class MotionSettings:
    default_speed: float = 0.5      # 0.0–1.0 duty
    pwm_frequency_hz: int = 1000

    def __post_init__(self) -> None:
        if not 0.0 <= self.default_speed <= 1.0:
            raise ValueError("default_speed must be in [0.0, 1.0]")
        if self.pwm_frequency_hz <= 0:
            raise ValueError("pwm_frequency_hz must be > 0")


@dataclass(frozen=True)
class RAGSettings:
    # Offline BM25 retrieval over the Yotengrit corpus. corpus_path="" -> the loader
    # uses its repo-default (training/rag/yotengrit_corpus.json).
    enabled: bool = True
    corpus_path: str = ""
    top_k: int = 3
    min_score: float = 0.0       # a chunk must score strictly above this to be returned
    title_boost: int = 2         # heading tokens weighted Nx in the BM25 index

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be > 0")
        if self.min_score < 0:
            raise ValueError("min_score must be >= 0")
        if self.title_boost < 1:
            raise ValueError("title_boost must be >= 1")


@dataclass(frozen=True)
class Settings:
    llm: LLMEndpoints = field(default_factory=LLMEndpoints)
    safety: SafetySettings = field(default_factory=SafetySettings)
    motion: MotionSettings = field(default_factory=MotionSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)


def load_settings() -> Settings:
    """Return effective settings. Stub: returns defaults until config loading lands."""
    return Settings()
