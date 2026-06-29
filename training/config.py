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
    tag: str = ""                  # experiment label -> output subdir (set via --tag/--preset)

    # GGUF quantizations to export: Q4_K_M for the Pi 5 edge, Q8_0 for the CAX31.
    gguf_quants: tuple[str, ...] = ("q4_k_m", "q8_0")

    def path(self, rel: str) -> Path:
        return HERE / rel


# Candidate base models — the comparison is not limited to two. Add an entry to
# test 3-4 models; each becomes `python finetune.py --variant <key>`, then build
# an Ollama model `freedroid-<key>` and pass it to run_benchmark.py --models.
# DECISION (Hungarian persona benchmark): Llama won — asymmetric hybrid, llama8b on
# the cloud / llama (3.2 3B) on the edge; hence --variant defaults to "llama". The
# qwen/qwen7b entries stay for reproducibility. (See CLAUDE.md.)
VARIANTS: dict[str, TrainConfig] = {
    "qwen": TrainConfig(name="qwen2.5-3b",
                        base_model="unsloth/Qwen2.5-3B-Instruct-bnb-4bit"),
    "llama": TrainConfig(name="llama3.2-3b",
                         base_model="unsloth/Llama-3.2-3B-Instruct-bnb-4bit"),
    # Larger candidates to test the Hungarian-fluency ceiling (3B Hungarian is weak,
    # even untuned). batch_size=1 + grad_accum=8 keeps QLoRA inside a free Colab T4
    # (15 GB) at effective batch 8; gguf_quants=("q4_k_m",) skips the q8_0 export, which
    # for an 8B is RAM/disk-heavy on a T4 and unneeded to benchmark. NB: the Pi 5 can't
    # run these in real time -> CLOUD-ONLY / hybrid candidates, not edge. (Llama "8B" = 3.1.)
    "qwen7b": TrainConfig(name="qwen2.5-7b",
                          base_model="unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
                          batch_size=1, grad_accum=8, gguf_quants=("q4_k_m",)),
    "llama8b": TrainConfig(name="llama3.1-8b",
                           base_model="unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit",
                           batch_size=1, grad_accum=8, gguf_quants=("q4_k_m",)),
    # Examples — uncomment / adjust to taste (verify the exact Unsloth repo id):
    # "gemma":   TrainConfig(name="gemma2-2b",
    #                        base_model="unsloth/gemma-2-2b-it-bnb-4bit"),
    # "phi":     TrainConfig(name="phi3.5-mini",
    #                        base_model="unsloth/Phi-3.5-mini-instruct-bnb-4bit"),
}

# Named hyperparameter recipes — `python finetune.py --variant qwen --preset gentle`.
# Explicit CLI flags override a preset; the preset name becomes the output-dir tag.
# "gentle" is the small-data anti-overfitting recipe (gentler than the v1 defaults that
# produced word-salad Hungarian): fewer epochs, lower LR, smaller LoRA rank. Note alpha
# tracks r (8/8 -> scaling 1.0) — dropping r alone while alpha stayed 16 would *raise*
# the adapter's influence (alpha/r), the opposite of "gentle".
PRESETS: dict[str, dict] = {
    "gentle": {"learning_rate": 5e-5, "epochs": 1,
               "lora_r": 8, "lora_alpha": 8, "lora_dropout": 0.05},
}

# Curated target modules for LoRA (all attention + MLP projections).
LORA_TARGET_MODULES: tuple[str, ...] = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
)
