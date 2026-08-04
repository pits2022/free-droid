#!/usr/bin/env python3
"""Egy MENTETT CHECKPOINT (epoch) exportálása GGUF-ba — a v11 epoch-választáshoz.

MIÉRT KELL: a `finetune.py` a `save_pretrained_gguf`-ot a memóriában lévő, tanítás
VÉGI modellre hívja. A `save_strategy="epoch"` ment ugyan epochonként adaptert a
`checkpoints/checkpoint-N/` alá, de azokból eddig nem vezetett út futtatható
modellhez — a benchmark pedig Ollamán keresztül mér, tehát GGUF kell.

MIT CSINÁL: betölti a base modellt, ráteszi a checkpoint LoRA-súlyait, és exportál.
Nem tanít, nem ír felül semmit a checkpointban.

    python export_checkpoint.py --variant llama --tag v11 --epoch 1
    python export_checkpoint.py --variant llama8b --tag v11 --epoch 2 --quants q4_k_m
    python export_checkpoint.py --variant llama --tag v11 --list   # mi van mentve

KÖLTSÉG, mielőtt mindet exportálod: az export a 4-bit adaptert 16-bitre olvasztja,
majd kvantál. A 3B-nél ez percek; a **8B-nél exportonként ~15-25 perc és több tíz GB
átmeneti hely**. A 3B-t érdemes mindhárom epochra kiexportálni (ott dől el az
epoch-szám), a 8B-nél csak a nyerteset és a szomszédját.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from config import LORA_TARGET_MODULES, VARIANTS, TrainConfig

HERE = Path(__file__).resolve().parent


_CKPT = re.compile(r"^checkpoint-(\d+)$")


def checkpoint_dirs(out: Path) -> list[Path]:
    """A mentett checkpointok, epoch-sorrendben (checkpoint-<lépés>).

    Szigorú minta + is_dir(): a `startswith("checkpoint-")` + `split("-")[1]` bármi
    másra ValueError-t dobna (letöltés-visszatöltés után maradt `checkpoint-100.zip`,
    `checkpoint-bak`, félbehagyott mentés). Traceback helyett maradjon üres a lista,
    és a hívó adjon értelmes hibaüzenetet — a felhasználó itt már elköltötte a GPU-időt.
    """
    ck = out / "checkpoints"
    if not ck.is_dir():
        return []
    parok = [(m, p) for p in ck.iterdir() if p.is_dir() and (m := _CKPT.match(p.name))]
    return [p for _, p in sorted(parok, key=lambda mp: int(mp[0].group(1)))]


def read_state_dict(ckpt: Path) -> dict:
    """A checkpoint adapter-súlyai. Külön függvény, hogy a VALIDÁCIÓ a nehéz
    (peft/torch/unsloth) importok ELŐTT futhasson — és tesztelhető legyen nélkülük."""
    st = ckpt / "adapter_model.safetensors"
    bin_ = ckpt / "adapter_model.bin"
    if st.exists():
        from safetensors.torch import load_file
        return load_file(str(st))
    if bin_.exists():
        import torch
        # weights_only=True: a .bin pickle, és a default unpickle tetszőleges kódot
        # futtatna. Itt csak tenzorok vannak, tehát nincs miért megengedni többet.
        return torch.load(str(bin_), map_location="cpu", weights_only=True)
    raise SystemExit(f"HIBA: nincs adapter-súly a checkpointban: {ckpt}")


def assert_lora_weights(sd: dict, ckpt: Path) -> int:
    """Hard fail, ha a state dictben nincs LoRA-tenzor.

    Ez a legdrágább CSENDES hiba ezen az úton: üres/rossz/base-modell checkpointtal a
    `set_peft_model_state_dict` SZÓ NÉLKÜL lefut, és a base modellt exportálnánk ki
    fine-tune gyanánt. A mérésben ez nem crashként jelenne meg, hanem úgy, hogy
    „a v11 nem hozott javulást" — 15-25 perc export és egy teljes benchmark-kör után.
    """
    lora = [k for k in sd if "lora_A" in k or "lora_B" in k]
    if not lora:
        raise SystemExit(
            f"HIBA: a checkpointban nincs LoRA-súly ({len(sd)} kulcs, egyik sem lora_A/B): "
            f"{ckpt}\n  Így a BASE modellt exportálnánk fine-tune gyanánt.")
    return len(lora)


def load_adapter_weights(model, ckpt: Path) -> None:
    """A checkpoint LoRA-súlyainak beolvasása a már felépített PEFT-modellbe.

    Nem `from_pretrained`-del töltünk, mert a modellt az Unsloth már felpatchelte;
    csak a súlyokat cseréljük ki alatta.
    """
    sd = read_state_dict(ckpt)
    print(f"  LoRA-tenzor a checkpointban: {assert_lora_weights(sd, ckpt)}")

    from peft import set_peft_model_state_dict
    res = set_peft_model_state_dict(model, sd)
    nem_vart = getattr(res, "unexpected_keys", None)
    if nem_vart:
        print(f"figyelem: {len(nem_vart)} nem várt kulcs a checkpointban", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    ap.add_argument("--tag", default="", help="a futás címkéje (pl. v11)")
    ap.add_argument("--epoch", type=int, help="hányadik mentett checkpoint (1-től)")
    ap.add_argument("--quants", nargs="+", help="felülírja a variáns gguf_quants értékét")
    ap.add_argument("--list", action="store_true", help="csak sorold fel a checkpointokat")
    args = ap.parse_args()

    cfg: TrainConfig = VARIANTS[args.variant]
    label = f"{cfg.name}-{args.tag}" if args.tag else cfg.name
    out = cfg.path(cfg.output_dir) / label
    ckpts = checkpoint_dirs(out)
    if not ckpts:
        print(f"HIBA: nincs mentett checkpoint itt: {out / 'checkpoints'}\n"
              "  A futásnak save_strategy='epoch'-kal kellett mennie (finetune.py).",
              file=sys.stderr)
        return 1

    print(f"checkpointok ({label}):")
    for i, p in enumerate(ckpts, 1):
        print(f"  epoch {i}: {p.name}")
    if args.list:
        return 0
    if args.epoch is None:
        print("HIBA: add meg, melyik epoch kell (--epoch), vagy használd a --list-et.",
              file=sys.stderr)
        return 1
    if not 1 <= args.epoch <= len(ckpts):
        print(f"HIBA: --epoch {args.epoch} nincs (1..{len(ckpts)}).", file=sys.stderr)
        return 1

    ckpt = ckpts[args.epoch - 1]
    quants = tuple(args.quants) if args.quants else cfg.gguf_quants
    print(f"\nexportálás: {ckpt.name} (epoch {args.epoch}) -> {', '.join(quants)}")

    from unsloth import FastLanguageModel  # must precede trl/transformers/peft

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg.base_model, max_seq_length=cfg.max_seq_length, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=cfg.lora_r, lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout,
        target_modules=list(LORA_TARGET_MODULES),
        use_gradient_checkpointing="unsloth", random_state=cfg.seed)
    load_adapter_weights(model, ckpt)

    # Az adaptert IS mentsük külön: a HF Space az adaptert tölti be, nem a GGUF-ot,
    # és egy epoch-jelöltet ott is meg kell tudni nézni.
    adapter_dir = out / f"lora-adapter-e{args.epoch}"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"adapter -> {adapter_dir}")

    for quant in quants:
        print(f"exporting GGUF ({quant}) ...")
        model.save_pretrained_gguf(str(out / f"gguf-{quant}-e{args.epoch}"), tokenizer,
                                   quantization_method=quant)
    print(f"\nkész. Modelfile: python make_modelfile.py --variant {args.variant} "
          f"{out.name}/gguf-{quants[0]}-e{args.epoch}/<fájl>.gguf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
