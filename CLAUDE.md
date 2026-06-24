# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**free-droid** (a.k.a. **Szabi**) is a sovereign, open-source AI robot built for **Hacktivity 2026**: a tracked
robot driven by a self-fine-tuned 3B LLM, demonstrating digital sovereignty (the owner — the *Teremtő* / "Creator" —
is `root`, not a vendor cloud). It speaks Hungarian only, has a young female voice, and its ethics are grounded in
**Yotengrit** philosophy.

This is **not part of the `~/git/` K3S platform** — it is a standalone hobby/conference project. The parent
`~/git/CLAUDE.md` workspace conventions still apply (feature branches, no auto-push, lint before commit).

## Source of truth — read this first

**`docs/free-droid.md` is the authoritative project specification (v2.0).** It is the full hardware + software + IaC
plan and the phased build checklist. When the spec and the code disagree, **the spec wins** and the code should be
brought into line with it.

The IaC under `infra/` has been **aligned to the v2.0 spec** (it was previously an outdated "Mother-Child" design).
What changed and what is intentionally still a placeholder:

| Topic | State |
| :--- | :--- |
| LLM | ✅ Parameterized to a **3B** base model (`ai_stack` role defaults: `cloud_ollama_model` / `edge_ollama_model`, default `qwen2.5:3b`). Base model is still **A/B-undecided** (Qwen 2.5 3B vs Llama 3.2 3B) — keep it a one-line swap. |
| Fine-tuned model | ⏳ The Ansible registry-pull is a **bring-up placeholder**; the real flow loads the fine-tuned **GGUF via an Ollama Modelfile** (not yet wired up). |
| Motion stack | ✅ **No ROS 2.** `ros2_setup` removed; replaced by `edge_robot` (plain Python venv, `lgpio`, no `rclpy`). ROS 2 is a later-roadmap port, out of Hacktivity scope. |
| WireGuard | ✅ `10.0.0.1` (cloud `mother-001`) ↔ `10.0.0.2` (edge `child-001`), `10.0.0.0/24` subnet. |
| Cloud location | `nbg1` (Terraform). The spec does not mandate a location — leave unless told otherwise. |

> `GEMINI.md`, `PROJECT_BRIEF.md`, and `CONTEXT.md` describe the **legacy** design — treat them as historical, not
> current (`GEMINI.md`'s overview header has been corrected to match). `README.md` matches the v2.0 spec.

## Architecture (per the v2.0 spec)

**Hybrid cloud-edge.** Same fine-tuned 3B model runs in both places; a Python orchestrator on the Pi picks the source:

- **Cloud (Hetzner GEX44):** inference only, via Ollama (Q8/f16). The cloud **never** fine-tunes.
- **Edge (Raspberry Pi 5, 8GB):** the same model at Q4_K_M, fully offline, as fallback.
- **Fine-tuning happens on Google Colab** (free T4) with Unsloth QLoRA — never on the GEX44.
- **Fallback ladder:** cloud (WireGuard up) → edge (offline) → "safe mode" (canned replies, motion disabled).

**Layered motion control — the LLM never drives motors directly:**

1. **LLM ("soul")** — intent + persona; emits a `<tool>function(param=value)</tool>` call.
2. **Control layer ("body", Python)** — deterministically turns tool calls into GPIO/PWM (Cytron HAT-MDD10).
3. **Safety watchdog ("reflex")** — HC-SR04P ultrasonic sensors on a *separate thread*; obstacle under threshold →
   immediate `stop()`, bypassing the LLM entirely.

Known tools: `move()`, `turn()`, `stop()`, `camera()`, `set_speed()`, `set_mode()`, `request_navigation_help()`,
`scan_wifi()`. The tool parser must be robust (tolerate extra whitespace / quote variants).

**Voice pipeline (fully offline on the Pi):** wake word `"Szabi"` (openWakeWord) → STT Whisper.cpp (Hungarian) →
LLM (cloud or edge) → TTS Piper (`hu_HU-anonymous-medium`, pitch-tuned younger) → tool execution.

**Target `robot/` module layout** (RPi control software, not yet built): `orchestrator/` (main async loop + fallback),
`motion/` (Cytron HAT, lgpio-based), `safety/` (ultrasonic watchdog thread), `voice/` (wake/STT/TTS/VAD),
`llm/` (cloud+edge client), `tools/` (parser + handlers), `config/` (GPIO pinout, thresholds, audio params — build this
first; every other module reads from it).

## Security & sovereignty invariants (do not violate)

- **`scan_wifi()` is read-only.** It runs `nmcli -t -f SSID,SIGNAL,SECURITY dev wifi` and lists networks with their
  security level. It must **never** connect, handle passwords, or expose an injection surface.
- **The robot never joins a network from a spoken command.** Network setup is always manual over a trusted channel.
- **Safety watchdog is independent of the LLM** — an obstacle stops the robot regardless of what the model says.

## Repository layout (actual, on disk)

- `docs/free-droid.md` — **the spec** (authoritative).
- `infra/terraform/` — Hetzner provisioning (`main.tf` + S3 state backend; `cloud/` module).
- `infra/ansible/` — `site.yml` + roles `wireguard_setup`, `ai_stack`, `edge_robot`.
- `training/` — fine-tuning. `dataset/` holds `freedroid_full.json` (615 ex.), `train.jsonl` (553), `val.jsonl` (62),
  `expansion_only.json`. `old/` is superseded per-category data. Also `persona_benchmark.json` (25 Q for the A/B model
  test) and `ertekelo_sablon.md` (scoring template). Spec also references `colab_finetune.ipynb` + `Modelfile` (not yet present).
- `robot/` — RPi 5 Python control software. **Not yet built** (Phase 4 — depends on hardware + fine-tuned model + cloud).
- `README.md` (English, matches spec) · `GEMINI.md` / `PROJECT_BRIEF.md` / `CONTEXT.md` (legacy, historical).
- `.env` is git-ignored; `infra/terraform/.tfvars` holds `hcloud_token` — **never commit secrets**.

## Commands

### Terraform (`infra/terraform/`)
```bash
cd infra/terraform
terraform init          # uses an S3 backend (AWS profile "terraform-s3-access") + hcloud
terraform fmt -recursive
terraform plan
terraform apply         # creates the GEX44, then auto-runs the Ansible site.yml via local-exec
```
Requires `hcloud_token` (in `.tfvars`) and AWS S3 access for remote state.

### Ansible (`infra/ansible/`)
```bash
# inventory.ini is generated by Terraform (groups: [cloud]=mother-001, [edge]=child-001)
cd infra/ansible
ansible-playbook --syntax-check -i inventory.ini site.yml
ansible-playbook -i inventory.ini site.yml
ansible-playbook -i inventory.ini site.yml --limit cloud   # cloud only
# Swap the base model without editing roles:
ansible-playbook -i inventory.ini site.yml -e edge_ollama_model=llama3.2:3b
```

### Fine-tuning (Google Colab, not local)
Unsloth QLoRA notebook on a free T4. Base model is a one-line swap (Qwen 2.5 3B vs Llama 3.2 3B). Train on
`training/dataset/train.jsonl`, validate on `val.jsonl`. Suggested start: `epochs=2–3, lr=2e-4, r=16, max_seq_length=2048`.
**Don't chase low loss** (overfitting → robotic, repetitive persona); measure on the validation set. Export GGUF
(Q4_K_M for edge, Q8/f16 for cloud) → Ollama `Modelfile`. A **"red team" pass** (provocative/off-topic questions) is
mandatory before the demo.

### A/B model evaluation
Run the 25 questions in `training/persona_benchmark.json` against both fine-tuned candidates, score with
`training/ertekelo_sablon.md` (6 dimensions, 1–5). The decision is made on this **Hungarian persona benchmark, not generic
benchmarks** — and must NOT be finalized until the A/B test concludes.

## Persona & language rules (matter for any dataset/prompt/TTS work)

- The robot is **Free-Droid**, nicknamed **Szabi** (from *Szabadság*, "freedom"); young female voice.
- It always addresses its creator as **Teremtő** ("Creator") — never by name.
- **Hungarian only** — this is part of the sovereignty message, not a limitation (the Creator interprets to English live).
- Yotengrit's dualism is **complementary** (forces add up / reinforce), **not** oppositional like yin-yang — get this
  right in any dataset or prompt edit. Core motifs: the "three reeds" (Love, Wisdom, Truth) and *"Mindent szabad, ami nem
  árt másnak"* ("everything is permitted that harms no other") — directly tied to the Szabi name.
- The fine-tune teaches **persona and values, not facts** (knowledge → RAG; style/reasoning → fine-tuning).

## Conventions

- **GPL-3.0** licensed.
- Feature branches only; never commit to `main` directly. Do not push automatically. Lint before committing.
- Per the workspace rule, update the `free-droid` section of `~/git/WORKFLOW.md` before ending a session
  (create the section if missing).
