#!/usr/bin/env python3
"""Ollama Modelfile-t generál egy GGUF-exporthoz, a VARIÁNSHOZ TARTOZÓ rendszerprompttal.

A modell a tanítási rendszerprompttal együtt tanult (finetune.py a chat-template system
üzenetébe teszi). Ha futtatáskor más SYSTEM kerül a Modelfile-ba, a modell más kontextust
kap, mint amin tanult — csendben romlik a viselkedés. 2026-07-27 óta a prompt VARIÁNSONKÉNT
más (a 3B a rövidített system_prompt_3b.txt-t kapja), így a párosítást nem érdemes kézzel
csinálni: ez a szkript a config.py-ból veszi.

Az Unsloth-exportált Modelfile_<gguf> NEM használható: nincs benne SYSTEM, és temperature
1.5-öt hoz (llama.cpp export-default), amitől a mérés szórása elmossa a különbségeket.

    python make_modelfile.py --variant llama   tests/v9/llama-3b/unsloth.Q4_K_M.gguf
    python make_modelfile.py --variant llama8b tests/v9/llama-8b/unsloth.Q4_K_M.gguf
    # majd:  cd tests/v9/llama-3b && ollama create szabi-3b-v9 -f Modelfile_szabi-3b-v9
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from config import VARIANTS

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gguf", type=Path, help="a GGUF export útvonala")
    ap.add_argument("--variant", required=True, choices=sorted(VARIANTS),
                    help="melyik TrainConfig — ez dönti el a rendszerpromptot")
    ap.add_argument("-o", "--out", type=Path, help="kimenet (alap: a GGUF mellé Modelfile_<név>)")
    args = ap.parse_args()

    cfg = VARIANTS[args.variant]
    template = (HERE / "Modelfile").read_text(encoding="utf-8")
    prompt = cfg.path(cfg.system_prompt).read_text(encoding="utf-8").strip()

    # A sablonból csak a FROM és a SYSTEM cserélődik; a TEMPLATE/stop/PARAMETER marad.
    out = re.sub(r"^FROM .*$", f"FROM ./{args.gguf.name}", template, count=1, flags=re.M)
    # FÜGGVÉNYES csere, nem string: az `re.subn` a csere-STRINGBEN feldolgozza a
    # backslash-eket (\1, \g<...>), tehát egy promptbeli `\` vagy elrontaná a szöveget,
    # vagy `re.error: bad escape`-et dobna. A lambda visszatérési értékét szó szerint
    # veszi, így nem kell escape-elni (és nem lehet dupla-escape hibát véteni sem).
    out, n = re.subn(r'SYSTEM """.*?"""', lambda _m: f'SYSTEM """{prompt}"""',
                     out, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("a Modelfile sablonban nincs pontosan egy SYSTEM blokk")
    header = (f"# GENERÁLT — make_modelfile.py --variant {args.variant}\n"
              f"# rendszerprompt: {cfg.system_prompt} ({len(prompt)} karakter) — EZZEL tanult a modell.\n")

    dest = args.out or args.gguf.with_name(f"Modelfile_{args.gguf.stem}")
    dest.write_text(header + out, encoding="utf-8")
    print(f"írva: {dest}\n  variáns: {args.variant} ({cfg.name})\n  prompt:  {cfg.system_prompt}")


if __name__ == "__main__":
    main()
