"""Fine-tuning configuration. The base-model A/B swap is a one-line change here.

Edit a hyperparameter once, run both variants on the same data, compare on the
Hungarian persona benchmark (persona_benchmark.json + ertekelo_sablon.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class TrainConfig:
    name: str                      # short label used in output paths
    base_model: str                # Unsloth 4-bit repo id

    # QLoRA / training hyperparameters (spec defaults; don't chase low loss).
    max_seq_length: int = 2048
    lora_r: int = 16
    lora_alpha: int = 16
    lora_dropout: float = 0.0
    epochs: int = 2
    learning_rate: float = 2e-4
    batch_size: int = 2
    grad_accum: int = 4            # effective batch = batch_size * grad_accum
    warmup_ratio: float = 0.05
    weight_decay: float = 0.01
    seed: int = 3407

    # Data (Alpaca format: instruction / input / output), resolved to this dir.
    train_file: str = "dataset/train.jsonl"
    val_file: str = "dataset/val.jsonl"
    output_dir: str = "outputs"

    # GGUF quantizations to export: Q4_K_M for the Pi 5 edge, Q8_0 for the CAX31.
    gguf_quants: tuple[str, ...] = ("q4_k_m", "q8_0")

    def path(self, rel: str) -> Path:
        return HERE / rel


# A/B candidates — see CLAUDE.md: model choice is NOT final until the benchmark decides.
VARIANTS: dict[str, TrainConfig] = {
    "qwen": TrainConfig(name="qwen2.5-3b",
                        base_model="unsloth/Qwen2.5-3B-Instruct-bnb-4bit"),
    "llama": TrainConfig(name="llama3.2-3b",
                         base_model="unsloth/Llama-3.2-3B-Instruct-bnb-4bit"),
}

# Curated target modules for LoRA (all attention + MLP projections).
LORA_TARGET_MODULES: tuple[str, ...] = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
)
