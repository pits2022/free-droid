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
| Cloud server | ✅ **CAX31** (`var.cloud_server_type`, `cax41` for more headroom) in `nbg1`. **Supersedes the spec's GEX44**, which is the Hetzner dedicated GPU line and is not provisionable via the hcloud Cloud API. CAX31/41 are ARM64, CPU-only. |
| Cloud lifecycle | ✅ Disposable by design: `terraform destroy` removes only the cloud server + its net/firewall. The Pi is Ansible-only, never terraform-managed — destroy can't touch it. Recreating the cloud mints a new WireGuard key → re-run the `wireguard_setup` role on the Pi to restore the tunnel. |

> `GEMINI.md`, `PROJECT_BRIEF.md`, and `CONTEXT.md` describe the **legacy** design — treat them as historical, not
> current (`GEMINI.md`'s overview header has been corrected to match). `README.md` matches the v2.0 spec.

## Architecture (per the v2.0 spec)

**Hybrid cloud-edge.** Same fine-tuned 3B model runs in both places; a Python orchestrator on the Pi picks the source:

- **Cloud (Hetzner CAX31/41 — ARM64, CPU-only):** inference only, via Ollama (Q8/f16, on CPU). The cloud **never**
  fine-tunes. (GEX44 from the spec is unavailable on the hcloud Cloud API; CAX31/41 supersede it — see below.)
- **Edge (Raspberry Pi 5, 8GB):** the same model at Q4_K_M, fully offline, as fallback.
- **Fine-tuning happens on Google Colab** (free T4) with Unsloth QLoRA — never on the cloud server.
- **Fallback ladder:** cloud (WireGuard up) → edge (offline) → "safe mode" (canned replies, motion disabled).
- **Health checks (`freedroid.health`):** a `freedroid-health` self-check runs at boot + every 10 min (systemd timer)
  over network/hardware/software layers. Cloud is on-demand, so cloud checks are WARNING (edge covers it); the edge
  stack + safety hardware + local control are CRITICAL. A vital failure → self-heal (restart the service) → re-check →
  safe-mode (`/run/freedroid/safe_mode` flag) if still down. Status → `/run/freedroid/health.json` + journald.

**Layered motion control — the LLM never drives motors directly:**

1. **LLM ("soul")** — intent + persona; emits a `<tool>function(param=value)</tool>` call.
2. **Control layer ("body", Python)** — deterministically turns tool calls into GPIO/PWM (Cytron HAT-MDD10).
3. **Safety watchdog ("reflex")** — HC-SR04P ultrasonic sensors on a *separate thread*; obstacle under threshold →
   immediate `stop()`, bypassing the LLM entirely.

Known tools: `move()`, `turn()`, `stop()`, `camera()`, `set_speed()`, `set_mode()`, `request_navigation_help()`,
`scan_wifi()`, `set_oracle()`. The tool parser must be robust (tolerate extra whitespace / quote variants).

**Voice pipeline (fully offline on the Pi):** wake word `"Szabi"` (openWakeWord) → STT Whisper.cpp (Hungarian) →
LLM (cloud or edge) → TTS Piper (`hu_HU-anonymous-medium`, pitch-tuned younger) → tool execution.

**Target `robot/` module layout** (RPi control software — mostly scaffold, but `rag/` is implemented + tested): `orchestrator/` (main async loop + fallback),
`motion/` (Cytron HAT, lgpio-based), `safety/` (ultrasonic watchdog thread), `voice/` (wake/STT/TTS/VAD),
`llm/` (cloud+edge client), `tools/` (parser + handlers), `rag/` (offline BM25 retrieval over the Yotengrit corpus:
chunker, Hungarian normalizer, self-contained Okapi BM25, grounding-prompt builder), `config/` (GPIO pinout, thresholds, audio params — build this
first; every other module reads from it), `oracle/` (**optional** "Tudók" external-LLM routing — see below).

## Security & sovereignty invariants (do not violate)

- **`scan_wifi()` is read-only.** It runs `nmcli -t -f SSID,SIGNAL,SECURITY dev wifi` and lists networks with their
  security level. It must **never** connect, handle passwords, or expose an injection surface.
- **The robot never joins a network from a spoken command.** Network setup is always manual over a trusted channel.
- **Safety watchdog is independent of the LLM** — an obstacle stops the robot regardless of what the model says.
- **"Tudók" oracle routing (`oracle/`, `set_oracle()`) is OFF by default and OFF on the demo.** It lets Szabi "cheat"
  off a bigger external model (default Anthropic Opus) on hard questions, then re-filter the raw answer through her
  Yotengrit persona. It breaks the sovereignty principle (external API), so it is **family/`extended` mode only** —
  the Hacktivity demo runs `mode: sovereign`. The orchestrator (not the 3B model) owns the two-step call; the LLM only
  emits a `<puska/>` hint. `provider: "ollama"` keeps it sovereign (a bigger *local* model).

## Repository layout (actual, on disk)

- `docs/free-droid.md` — **the spec** (authoritative).
- `infra/terraform/` — Hetzner provisioning (`main.tf` + S3 state backend; `cloud/` module).
- `infra/ansible/` — `site.yml` + roles `wireguard_setup`, `ai_stack`, `edge_robot`.
- `training/` — fine-tuning. `dataset/` holds `freedroid_full.json` (744 ex.), `train.jsonl` (670), `val.jsonl` (74),
  `expansion_only.json` (92 new). Categories include `oracle_routing` (15) — so the dataset uses `set_oracle()` and the
  `<puska/>` hint (the grammar contract test guards this). `old/` is superseded per-category data. Also
  `persona_benchmark.json` (25 Q A/B test) + `ertekelo_sablon.md`, and the Unsloth scaffold (`finetune.py`, `config.py`,
  `colab_finetune.ipynb`, `colab_finetune_szabi.ipynb` (the v2 fine-tune on the 745-ex dataset), `Modelfile`, `system_prompt.txt`).
  The dataset since gained a terse-góbés persona voice (`persona_voice.md`), a tool-call expansion (`dataset/tool_calls_expansion.json` — tool examples 6%→17%), and a RAG-grounding category (`dataset/rag_category.json`, "válasz adott kontextusból"). `dataset/merge_and_split.py` merges the staged `tool_calls_expansion.json` + `rag_category.json` into `freedroid_full.json` and regenerates the split. RAG knowledge source: `rag/yotengrit.md` → `rag/yotengrit_corpus.json` (31 chunks, `python -m freedroid.rag.corpus`).
- `robot/` — RPi 5 Python control software (`freedroid` package, `src/freedroid/`). **Scaffold only** —
  interfaces + `NotImplementedError` stubs; `config/` carries the real pinout/tunables. Pi-only (direct `lgpio`,
  no off-Pi mock), managed with **uv**. Implementation is Phase 4 (needs hardware + fine-tuned model + cloud).
Exception: `rag/` is fully implemented + unit-tested (pure-python, off-Pi) — chunker, Hungarian-normalized self-contained
BM25 retriever, grounding-prompt builder; only wiring it into the orchestrator loop remains Phase 4.
- `README.md` (English, matches spec) · `GEMINI.md` / `PROJECT_BRIEF.md` / `CONTEXT.md` (legacy, historical).
- `.env` is git-ignored; `infra/terraform/.tfvars` holds `hcloud_token` — **never commit secrets**.

## Commands

### Terraform (`infra/terraform/`)
```bash
cd infra/terraform
terraform init          # uses an S3 backend (AWS profile "terraform-s3-access") + hcloud
terraform fmt -recursive
terraform plan
terraform apply         # creates the CAX31, then auto-runs the Ansible site.yml (cloud) via local-exec
terraform apply -var cloud_server_type=cax41   # bigger cloud box
terraform destroy       # tears down ONLY the cloud server — the Pi (Ansible-only) is untouched
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

### Robot control software (`robot/`)
```bash
cd robot
uv sync --extra dev     # create the project venv (.venv) + install
uv run freedroid        # run the orchestrator (stub today)
uv run freedroid-health # run the vital-function health check once
uv run pytest           # full suite (green; Phase-4 specs xfail, Pi-only specs skip)
uv run pytest -m phase4 # just the TDD harness
uv run ruff check .
```
Tests use `xfail_strict=true`: Phase-4 behavioural specs (`test_parser_behaviour`,
`test_phase4_hardware`) xfail until implemented, then flip to a hard failure that forces
removing the marker. Hardware-controller specs are `@requires_pi` (skipped off-Pi).
Pi-only: modules are written directly against `lgpio`; importing the package works off-Pi (no top-level hardware
imports), but instantiating a controller raises `NotImplementedError` until implemented. Build order:
`config` → `motion`+`safety` → `tools` → `llm` → `voice` → `orchestrator`.

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
- The fine-tune teaches **persona and values, not facts** (knowledge → RAG, implemented in `robot/src/freedroid/rag/`; style/reasoning → fine-tuning).

## Known follow-ups (deferred)

Conscious gaps from the PR #4 review — not bugs, but things a future session should know:

- **`scripts/_hw.py` gpiochip detection** — on the Pi 5 the 40-pin bank may be `gpiochip0` or
  `gpiochip4` and both open. We use a `FREEDROID_GPIOCHIP` env override + a diagnostic print, **not**
  full RP1-label detection (couldn't verify on hardware). Finish the label-based pick once on a Pi.
- **`freedroid.health.check_orchestrator_service` is CRITICAL when down** — so before the `freedroid`
  orchestrator service exists (Phase 4.3), a real Pi reports unhealthy and enters safe-mode. This is
  **accepted/intended** (no orchestrator = not functional). The review only removed the *restart churn*
  (`remediate` no-ops when the unit isn't installed); do **not** "fix" the severity/skip — it's a decision.
- **Minor, left as-is:** `check_package_import` is a near-tautological venv-intact canary (cheap, fine);
  `tests/test_grammar.py`'s `KNOWN_TOOLS` is a hardcoded list (it mirrors the spec's tool set, not code).

## Conventions

- **GPL-3.0** licensed.
- Feature branches only; never commit to `main` directly. Do not push automatically. Lint before committing.
- Per the workspace rule, update the `free-droid` section of `~/git/WORKFLOW.md` before ending a session
  (create the section if missing).
