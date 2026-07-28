#!/usr/bin/env python3
"""Fine-tune a base 3B model on the Free-Droid (Szabi) dataset with Unsloth QLoRA.

GPU-only (CUDA) — runs on Colab's free T4, NOT on the Pi or the CAX31. The thin
notebook (colab_finetune.ipynb) installs Unsloth and calls this.

    python finetune.py --variant llama     # the chosen 3B base (or: --variant qwen)
    python finetune.py --variant llama --epochs 3 --lr 1e-4

Trains WITH the inference-time system prompt so the model learns to answer in persona
given that system message. The prompt file is PER-VARIANT (TrainConfig.system_prompt):
the 8B uses system_prompt.txt, the 3B the shortened system_prompt_3b.txt. Keep each in
sync with the Ollama Modelfile SYSTEM you serve that variant with — a mismatch means the
model meets a different system message at inference than it trained on.
Exports GGUF (q4_k_m for edge, q8_0 for cloud) + the LoRA adapter.
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path

from config import LORA_TARGET_MODULES, PRESETS, VARIANTS, TrainConfig

HERE = Path(__file__).resolve().parent


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
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="llama")
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

    # Per-variant (cfg.system_prompt): the 3B trains on the shortened prompt. Whatever
    # is baked in here MUST end up in the Ollama Modelfile SYSTEM for that variant.
    system_prompt = cfg.path(cfg.system_prompt).read_text(encoding="utf-8").strip()
    print(f"system prompt: {cfg.system_prompt} ({len(system_prompt)} karakter)")

    def to_text(example: dict) -> dict:
        user = example["instruction"]
        if example.get("input"):
            user = f"{user}\n\n{example['input']}"
        messages = [
            {"role": "system", "content": system_prompt},
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


# Llama-3 chat-template markers — must match what tokenizer.apply_chat_template renders
# (and the TEMPLATE block in training/Modelfile). Both variants are Llama-3.x.
_INSTRUCTION_PART = "<|start_header_id|>user<|end_header_id|>\n\n"
_RESPONSE_PART = "<|start_header_id|>assistant<|end_header_id|>\n\n"

# A correctly masked example trains on the answer only. Measured on the 915-example set,
# the answer is 4.1% of the sequence with the canonical prompt and 6.1% with the 3B's
# shortened one, so anything above this is masking that did not take effect.
_MAX_TRAINED_SHARE = 0.5


def _mask_prompt_tokens(trainer, tokenizer):
    """Compute the loss on the ANSWER only — mask the system prompt and the question.

    Until v9 this was missing, so the loss ran over the whole rendered sequence. Since the
    system prompt sits in EVERY example, the answer was only ~4-6% of the tokens: the run
    spent ~95% of its capacity learning to reproduce the system prompt. That is not a
    subtle inefficiency — it is the direct cause of the prompt recitation (the v8 3B quoted
    the prompt verbatim in 8 of 40 red-team answers), of the second-person slips ("Fiú
    vagy." — continuing the input instead of answering it), and of the implausibly low eval
    loss (8B: 0.147, i.e. mostly predicting a constant prefix).

    The dangerous failure mode is a SILENT no-op: if the marker strings stop matching the
    chat template, masking does nothing and we are back to the old behaviour with no
    signal at all — which is exactly how this went unnoticed for four versions. So the
    result is verified and the run aborts rather than training a lie.
    """
    from unsloth.chat_templates import train_on_responses_only

    trainer = train_on_responses_only(trainer, instruction_part=_INSTRUCTION_PART,
                                      response_part=_RESPONSE_PART)

    n = min(8, len(trainer.train_dataset))
    verify_masking([trainer.train_dataset[i]["labels"] for i in range(n)])
    return trainer


def verify_masking(label_batches) -> float:
    """Share of tokens that carry loss; raise if masking clearly did not take effect.

    Split out from _mask_prompt_tokens so it is testable without a GPU or Unsloth
    (see test_finetune_masking.py) — the guard is the whole point, so it needs a test.
    """
    total = sum(len(b) for b in label_batches)
    trained = sum(1 for b in label_batches for t in b if t != -100)
    share = trained / total if total else 0.0
    print(f"response masking: {trained}/{total} token tanul ({100 * share:.1f}%) "
          f"— {len(label_batches)} minta alapján")

    if trained == 0:
        raise RuntimeError(
            "response masking: MINDEN token maszkolva — a válasz-marker nem illeszkedik "
            f"a chat-templatehez ({_RESPONSE_PART!r}). A futás így semmit nem tanulna.")
    if share > _MAX_TRAINED_SHARE:
        raise RuntimeError(
            f"response masking: NEM történt maszkolás (a tokenek {100 * share:.1f}%-ára "
            "van loss). A marker-stringek nem illeszkednek a chat-templatehez — javítsd "
            "őket, ne futtasd így: ez a v9-ig tartó hibás állapot.")
    return share


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
    trainer = _mask_prompt_tokens(trainer, tokenizer)
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
