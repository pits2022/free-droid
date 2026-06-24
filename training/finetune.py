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
from pathlib import Path

from config import LORA_TARGET_MODULES, VARIANTS, TrainConfig

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT = (HERE / "system_prompt.txt").read_text(encoding="utf-8").strip()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="qwen")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--lora-r", type=int, dest="lora_r")
    ap.add_argument("--max-seq-length", type=int, dest="max_seq_length")
    ap.add_argument("--no-gguf", action="store_true", help="skip GGUF export (faster smoke run)")
    return ap.parse_args()


def resolve_config(args: argparse.Namespace) -> TrainConfig:
    cfg = VARIANTS[args.variant]
    overrides = {k: v for k, v in vars(args).items()
                 if k in {"epochs", "lr", "lora_r", "max_seq_length"} and v is not None}
    if "lr" in overrides:
        overrides["learning_rate"] = overrides.pop("lr")
    from dataclasses import replace
    return replace(cfg, **overrides) if overrides else cfg


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


def run(cfg: TrainConfig, export_gguf: bool = True) -> Path:
    import torch
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    print(f"== fine-tuning {cfg.name} from {cfg.base_model} ==")
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
    out = cfg.path(cfg.output_dir) / cfg.name
    out.mkdir(parents=True, exist_ok=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds["train"],
        eval_dataset=ds["val"],
        args=SFTConfig(
            dataset_text_field="text",
            max_seq_length=cfg.max_seq_length,
            per_device_train_batch_size=cfg.batch_size,
            gradient_accumulation_steps=cfg.grad_accum,
            num_train_epochs=cfg.epochs,
            learning_rate=cfg.learning_rate,
            warmup_ratio=cfg.warmup_ratio,
            weight_decay=cfg.weight_decay,
            logging_steps=10,
            eval_strategy="epoch",          # measure on the validation set
            optim="adamw_8bit",
            seed=cfg.seed,
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            output_dir=str(out / "checkpoints"),
            report_to="none",
        ),
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
