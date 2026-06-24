"""Runtime tunables with sane defaults. Override via env / config file later.

Values not fixed by the spec (e.g. the stop threshold) are placeholders to be
confirmed during bring-up.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMEndpoints:
    # Cloud Ollama is reachable over WireGuard; edge Ollama is loopback-only.
    cloud_url: str = "http://10.0.0.1:11434"
    edge_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b"   # placeholder — final = fine-tuned GGUF Modelfile tag
    cloud_timeout_s: float = 8.0


@dataclass(frozen=True)
class SafetySettings:
    # TODO(confirm with Creator): real stop distance during bring-up.
    stop_threshold_cm: float = 25.0
    poll_interval_s: float = 0.05   # watchdog thread cadence
    # Per-sensor overrides, e.g. {"front": 30.0}
    per_sensor_cm: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MotionSettings:
    default_speed: float = 0.5      # 0.0–1.0 duty
    pwm_frequency_hz: int = 1000


@dataclass(frozen=True)
class Settings:
    llm: LLMEndpoints = field(default_factory=LLMEndpoints)
    safety: SafetySettings = field(default_factory=SafetySettings)
    motion: MotionSettings = field(default_factory=MotionSettings)


def load_settings() -> Settings:
    """Return effective settings. Stub: returns defaults until config loading lands."""
    return Settings()
