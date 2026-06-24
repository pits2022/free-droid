# training/ — fine-tuning the Free-Droid (Szabi) model

Teaches **persona and values** (not facts) onto a small base model via Unsloth QLoRA.
**GPU-only — runs on Google Colab's free T4**, never on the Pi or the CAX31 (both
are CPU/ARM). Unsloth is deliberately **not** a dependency of the deployed system.

## Files

| File | Purpose |
| :--- | :--- |
| `colab_finetune.ipynb` | Thin Colab runner: installs Unsloth, clones the repo, calls `finetune.py` |
| `finetune.py` | The training logic (load 4-bit base → LoRA → train → export GGUF + adapter) |
| `config.py` | Hyperparameters + the **A/B base-model swap** (one line) |
| `run_benchmark.py` | Runs **N** Ollama models through the 25-question benchmark → `benchmark_eredmeny.md` |
| `system_prompt.txt` | The persona system prompt used at train time (keep in sync with `Modelfile`) |
| `Modelfile` | Ollama export config (`ollama create szabi -f Modelfile`) |
| `requirements.txt` | Training deps (Colab); freeze exact versions after a known-good run |
| `dataset/` | 630 Hungarian examples, Alpaca format (`train.jsonl` 567 / `val.jsonl` 63) |
| `persona_benchmark.json` + `ertekelo_sablon.md` | 25-question A/B benchmark + scoring sheet |

## Run (on Colab, T4)

Open `colab_finetune.ipynb`, set Runtime → T4 GPU, run all. Or locally on a CUDA box:

```bash
cd training
pip install -r requirements.txt          # see notes; prefer Unsloth's installer on Colab
python finetune.py --variant qwen         # candidate 1
python finetune.py --variant llama        # candidate 2 (same data + hyperparams)
python finetune.py --variant qwen --epochs 3 --lr 1e-4   # override per run
python finetune.py --variant qwen --no-gguf              # quick smoke (skip export)
```

Outputs land in `training/outputs/<variant>/`: `gguf-q4_k_m/` (Pi edge), `gguf-q8_0/`
(CAX31 cloud), `lora-adapter/`. These are **git-ignored** — push to HF Hub or copy out.

## A/B decision

The base model (Qwen 2.5 3B vs Llama 3.2 3B) is **not final** — see `CLAUDE.md`. Train
both on the same data, score with `persona_benchmark.json` + `ertekelo_sablon.md` (6
dimensions, 1–5), measure tok/s + RAM on the Pi, then pick the winner and update the docs.
Don't chase low loss (overfitting → robotic, repetitive persona); 2 epochs often beats 3.

`run_benchmark.py` automates the asking for **any number of models** (2, 3, 4 …): build each
in Ollama, then run

```bash
ollama create freedroid-qwen  -f Modelfile   # FROM the Qwen GGUF
ollama create freedroid-llama -f Modelfile   # FROM the Llama GGUF
ollama create freedroid-gemma -f Modelfile   # …add as many as you train

python run_benchmark.py --models freedroid-qwen freedroid-llama freedroid-gemma --json-out
# → benchmark_eredmeny.md (fill the Pont columns by hand)
```

It puts every model's answer side by side per question (temperature=0.7, seed=42, identical
for fairness) with tok/s, leaving the score cells and the dimension summary for you to fill in.
With no `--models` it defaults to the two `freedroid-qwen` / `freedroid-llama`.

## Deploy

`ollama create szabi -f Modelfile` with `FROM` pointing at the chosen GGUF. On the
cluster this is the `ai_stack` Ansible role's job (load the GGUF via the Modelfile);
the registry pull there is just the bring-up placeholder until this lands.
