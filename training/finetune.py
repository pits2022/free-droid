#!/usr/bin/env python3
"""Fine-tune a base 3B model on the Free-Droid (Szabi) dataset with Unsloth QLoRA.

GPU-only (CUDA) — runs on Colab's free T4, NOT on the Pi or the CAX31. The thin
notebook (colab_finetune.ipynb) installs Unsloth and calls this.

    python finetune.py --variant qwen      # or: --variant llama
    python finetune.py --variant qwen --epochs 3 --lr 1e-4

Trains WITH the inference-time system prompt (system_prompt.txt) so the model
learns to answer in persona given that system message — keep it in sync with the
Ollama Modelfile. Exports GGUF (q4_k_m for edge, q8_0 for cloud) + the LoRA adapter.
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

from config import LORA_TARGET_MODULES, PRESETS, VARIANTS, TrainConfig

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT = (HERE / "system_prompt.txt").read_text(encoding="utf-8").strip()


# Hyperparameters the CLI can override (TrainConfig field -> argparse type). Adding a
# new tunable is one line here (the field must exist on TrainConfig); it then becomes a
# --flag and shows in the effective-config echo. Iteration order = echo display order.
HYPERPARAMS: dict[str, type] = {
    "epochs": int, "learning_rate": float,
    "lora_r": int, "lora_alpha": int, "lora_dropout": float,
    "batch_size": int, "grad_accum": int,
    "warmup_ratio": float, "weight_decay": float,
    "max_seq_length": int, "seed": int,
}
# Extra/short flag spellings for a field (keeps the documented --lr working).
ALIASES: dict[str, list[str]] = {"learning_rate": ["--learning-rate", "--lr"]}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="qwen")
    ap.add_argument("--preset", choices=sorted(PRESETS),
                    help="named hyperparameter recipe; explicit flags override it")
    ap.add_argument("--tag", default=None,
                    help="output-dir suffix so experiments sit side by side (default: preset name)")
    for field, typ in HYPERPARAMS.items():
        ap.add_argument(*ALIASES.get(field, [f"--{field.replace('_', '-')}"]),
                        type=typ, dest=field, default=None)
    ap.add_argument("--no-gguf", action="store_true", help="skip GGUF export (faster smoke run)")
    return ap.parse_args()


def resolve_config(args: argparse.Namespace) -> TrainConfig:
    """Merge VARIANT defaults < preset < explicit CLI flags into one TrainConfig."""
    from dataclasses import replace

    cfg = VARIANTS[args.variant]
    overrides: dict = dict(PRESETS.get(args.preset, {}))
    overrides.update({f: getattr(args, f) for f in HYPERPARAMS
                      if getattr(args, f) is not None})
    overrides["tag"] = args.tag if args.tag is not None else (args.preset or "")
    return replace(cfg, **overrides)


def build_dataset(tokenizer, cfg: TrainConfig):
    """Load the Alpaca-format JSONL and render each row with the chat template."""
    from datasets import load_dataset

    def to_text(example: dict) -> dict:
        user = example["instruction"]
        if example.get("input"):
            user = f"{user}\n\n{example['input']}"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": example["output"]},
        ]
        return {"text": tokenizer.apply_chat_template(messages, tokenize=False)}

    files = {"train": str(cfg.path(cfg.train_file)), "val": str(cfg.path(cfg.val_file))}
    ds = load_dataset("json", data_files=files)
    return ds.map(to_text, remove_columns=ds["train"].column_names)


def _pick_kwarg(target, names: tuple[str, ...]) -> str | None:
    """First of `names` that `target` (a class or callable) accepts, else None.

    TRL/transformers keep renaming kwargs (max_length<-max_seq_length,
    eval_strategy<-evaluation_strategy, processing_class<-tokenizer). List the
    modern name first; we pass whichever the installed version actually exposes,
    so one script tracks the moving Colab stack instead of pinning a version.
    """
    try:
        params = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return None
    return next((n for n in names if n in params), None)


def run(cfg: TrainConfig, export_gguf: bool = True) -> Path:
    from unsloth import FastLanguageModel  # must precede trl/transformers/peft so patches apply

    import torch
    from trl import SFTConfig, SFTTrainer

    label = f"{cfg.name}-{cfg.tag}" if cfg.tag else cfg.name
    print(f"== fine-tuning {label} from {cfg.base_model} ==")
    print("== effective hyperparameters ==")
    for field in HYPERPARAMS:
        print(f"  {field} = {getattr(cfg, field)}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg.base_model,
        max_seq_length=cfg.max_seq_length,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg.lora_r,
        lora_alpha=cfg.lora_alpha,
        lora_dropout=cfg.lora_dropout,
        target_modules=list(LORA_TARGET_MODULES),
        use_gradient_checkpointing="unsloth",
        random_state=cfg.seed,
    )

    ds = build_dataset(tokenizer, cfg)
    out = cfg.path(cfg.output_dir) / label
    out.mkdir(parents=True, exist_ok=True)

    sft_kwargs = dict(
        dataset_text_field="text",
        per_device_train_batch_size=cfg.batch_size,
        gradient_accumulation_steps=cfg.grad_accum,
        num_train_epochs=cfg.epochs,
        learning_rate=cfg.learning_rate,
        warmup_ratio=cfg.warmup_ratio,
        weight_decay=cfg.weight_decay,
        logging_steps=10,
        optim="adamw_8bit",
        seed=cfg.seed,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        output_dir=str(out / "checkpoints"),
        report_to="none",
    )
    # Map the kwargs TRL/transformers renamed across versions to whatever the
    # installed build accepts (see _pick_kwarg). Omit any the build doesn't expose
    # rather than hard-crash at construction.
    seq_kw = _pick_kwarg(SFTConfig, ("max_length", "max_seq_length"))
    if seq_kw:
        sft_kwargs[seq_kw] = cfg.max_seq_length
    eval_kw = _pick_kwarg(SFTConfig, ("eval_strategy", "evaluation_strategy"))
    if eval_kw:
        sft_kwargs[eval_kw] = "epoch"          # measure on the validation set

    tok_kw = _pick_kwarg(SFTTrainer, ("processing_class", "tokenizer")) or "processing_class"
    print(f"TRL compat: seq={seq_kw!r}, eval={eval_kw!r}, tokenizer={tok_kw!r}")

    trainer = SFTTrainer(
        model=model,
        train_dataset=ds["train"],
        eval_dataset=ds["val"],
        args=SFTConfig(**sft_kwargs),
        **{tok_kw: tokenizer},
    )
    trainer.train()

    adapter_dir = out / "lora-adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"saved LoRA adapter -> {adapter_dir}")

    if export_gguf:
        for quant in cfg.gguf_quants:
            print(f"exporting GGUF ({quant}) ...")
            model.save_pretrained_gguf(str(out / f"gguf-{quant}"), tokenizer,
                                       quantization_method=quant)
    return out


def main() -> None:
    args = parse_args()
    cfg = resolve_config(args)
    out = run(cfg, export_gguf=not args.no_gguf)
    print(f"done: {out}")


if __name__ == "__main__":
    main()
