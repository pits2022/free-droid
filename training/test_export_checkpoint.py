#!/usr/bin/env python3
"""Az export_checkpoint.py két törékeny pontja — GPU és peft/unsloth nélkül futtatható.

Futtatás: `python test_export_checkpoint.py` vagy `pytest test_export_checkpoint.py`.

Miért pont ez a kettő:
  1. `checkpoint_dirs` — a PR #36 review találata: a `split("-")[1]` bármi másra
     ValueError-t dobott (`checkpoint-100.zip`, `checkpoint-bak`). A felhasználó itt
     már elköltötte a GPU-időt; tracebackkel elbúcsúzni tőle a legrosszabb pillanat.
  2. `assert_lora_weights` — a CSENDES hiba: LoRA-súly nélküli state dicttel a base
     modellt exportálnánk fine-tune gyanánt, és ez a mérésben nem hibaként, hanem
     „a v11 nem hozott javulást"-ként jelenne meg.
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "export_checkpoint", Path(__file__).resolve().parent / "export_checkpoint.py")
ec = importlib.util.module_from_spec(_spec)
sys.modules["export_checkpoint"] = ec
_spec.loader.exec_module(ec)


def test_checkpoint_dirs_ignores_noise_and_sorts_by_step() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        ck = out / "checkpoints"
        ck.mkdir()
        for name in ("checkpoint-309", "checkpoint-103", "checkpoint-206"):
            (ck / name).mkdir()
        (ck / "checkpoint-bak").mkdir()        # nem szám a lépés helyén
        (ck / "checkpoint-99-step").mkdir()    # extra utótag
        (ck / "tmp-checkpoint-50").mkdir()     # félbehagyott HF-mentés
        (ck / "checkpoint-100.zip").write_text("x")  # FÁJL, nem könyvtár

        got = [p.name for p in ec.checkpoint_dirs(out)]
        assert got == ["checkpoint-103", "checkpoint-206", "checkpoint-309"], got


def test_checkpoint_dirs_empty_when_missing() -> None:
    with tempfile.TemporaryDirectory() as d:
        assert ec.checkpoint_dirs(Path(d)) == [], "checkpoints/ nélkül üres lista, nem hiba"


def test_lora_guard_rejects_state_dict_without_adapter() -> None:
    # Base-modell / üres checkpoint: van benne súly, de egyik sem LoRA.
    sd = {"model.layers.0.self_attn.q_proj.weight": object(),
          "model.embed_tokens.weight": object()}
    try:
        ec.assert_lora_weights(sd, Path("/tmp/checkpoint-1"))
    except SystemExit as e:
        assert "nincs LoRA-súly" in str(e), str(e)
        return
    raise AssertionError("LoRA-súly nélküli state dictnek hard failt kell okoznia — "
                         "különben a base modell megy ki fine-tune gyanánt")


def test_lora_guard_accepts_real_adapter() -> None:
    sd = {"base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight": object(),
          "base_model.model.model.layers.0.self_attn.q_proj.lora_B.weight": object(),
          "base_model.model.model.layers.0.self_attn.v_proj.lora_A.weight": object()}
    assert ec.assert_lora_weights(sd, Path("/tmp/checkpoint-1")) == 3


if __name__ == "__main__":
    test_checkpoint_dirs_ignores_noise_and_sorts_by_step()
    test_checkpoint_dirs_empty_when_missing()
    test_lora_guard_rejects_state_dict_without_adapter()
    test_lora_guard_accepts_real_adapter()
    print("MIND ZÖLD")
