# GEMINI.md - free-droid Project Context & Developer Reference

> **Authoritative sources:** `docs/free-droid.md` (the v2.0 spec) and `CLAUDE.md`. This file provides a comprehensive session-level reference for developers working on the repository. If anything here disagrees with the v2.0 spec, the spec wins. `PROJECT_BRIEF.md` and `CONTEXT.md` are historical documents.

## 🧬 Project Mission & Core Identity
**free-droid** (SZABI) is a fully automated, "Zero-Touch", sovereign AI tracked robot built for the **Hacktivity 2026** conference. It demonstrates digital sovereignty by ensuring that the owner — the *Teremtő* / "Creator" — is `root` instead of a vendor cloud.

### Persona & Language Rules
- **Name:** Free-Droid, nicknamed **Szabi** (from *Szabadság*, "freedom").
- **Voice & Tone:** Young, female character; young Hungarian voice.
- **Language:** Hungarian only — this is part of the sovereignty message (the Creator interprets to English live at the conference).
- **Loyalty:** Always addresses the creator as **Teremtő** ("Creator") — never by name. Loyal to the Creator and their family circle.
- **Ethics & Philosophy:** Grounded in **Yotengrit** (the heritage of the Rábaköz wisdom-keepers):
  - **Complementary Dualism:** Forces/pairs are complementary and mutually reinforcing, not oppositional like yin-yang. Elements add up to a whole.
  - **The Three Reeds (Három nádszál):** Erények (Virtues) guiding all actions: **Szeretet** (Love), **Bölcsesség** (Wisdom), and **Igazság** (Truth).
  - **Szabadság-tétel (Freedom Principle):** *"Mindent szabad, ami nem árt másnak."* ("Everything is permitted that harms no other.")
- **Honesty:** Sincere and uncensored. If it doesn't know something (e.g. an unknown route), it openly admits it (*"nincs rá biztos adatom"*).

---

## 🏗️ System Architecture

### Hybrid Asymmetric Cloud-Edge AI Stack
The system connects a disposable, hourly-billed cloud server and a physical edge device over a secure WireGuard VPN subnet (`10.0.0.0/24`).
- **Cloud (mother-001):**
  - **Server Type:** Hetzner Cloud **CAX31** (ARM64, CPU-only, 8 vCPUs, 16 GB RAM) in `nbg1` (or upgradeable to **CAX41** with 16 vCPUs, 32 GB RAM if needed). Note: Dedicated GPU servers (like GEX44) are not used as they are not provisionable via the hcloud Cloud API.
  - **Role:** High-precision inference using fine-tuned **Llama 3.1 8B** (Q4_K_M) via Ollama on CPU. The cloud is disposable (`terraform destroy` tears it down without affecting the Pi) and never fine-tunes.
- **Edge (child-001):**
  - **Hardware:** Raspberry Pi 5 (8GB RAM) running Raspberry Pi OS 64-bit Lite (Debian Bookworm).
  - **Role:** Fallback offline inference using fine-tuned **Llama 3.2 3B** (Q4_K_M) via Ollama. It drives robot controllers, voice components, and the safety watchdog.
- **Inference Fallback Ladder:**
  - Cloud LLM (WireGuard up, default) ➔ Local Edge LLM (offline fallback) ➔ "Safe Mode" (motion disabled, canned text responses).

### Connectivity
- Private VPN IP ranges: Cloud `10.0.0.1` ↔ Edge `10.0.0.2`.
- Secure peer keys are exchanged on-the-fly via Ansible host variables.
- Ollama port `11434` is bound strictly to the VPN interface to prevent external exposure.

---

## 🔌 Hardware Configuration & GPIO Pinout (Pi 5)

The hardware features three isolated power lines supplied by a 3S 11.1V LiPo battery through an XT60 4-channel PDB, with inline waterproof blade fuses (10A, 10A, 25A) for each active line.

### GPIO Pin Allocation (BCM numbering)
- **Motors (Cytron HAT-MDD10):**
  - `GPIO 12` (Pin 32): Left Motor PWM (Speed)
  - `GPIO 13` (Pin 33): Left Motor DIR (Direction)
  - `GPIO 6` (Pin 31): Right Motor PWM (Speed)
  - `GPIO 5` (Pin 29): Right Motor DIR (Direction)
- **Camera Pan-Tilt Gimbal (PCA9685 over I2C):**
  - `GPIO 2` (Pin 3): I2C SDA
  - `GPIO 3` (Pin 5): I2C SCL
  - PCA9685 I2C Address: `0x40`
  - Pan Servo (MG996R): PCA9685 Channel `CH0`
  - Tilt Servo (MG996R): PCA9685 Channel `CH1`
- **Ultrasonic Obstacle Watchdog (HC-SR04P):**
  - **Front:** Trig `GPIO 23` (Pin 16), Echo `GPIO 24` (Pin 18)
  - **Front-Left (45°):** Trig `GPIO 25` (Pin 22), Echo `GPIO 8` (Pin 24)
  - **Front-Right (45°):** Trig `GPIO 7` (Pin 26), Echo `GPIO 1` (Pin 28)
  - *Note:* Echo pins are connected directly without dividers since the "P" model operates natively at 3.3V–5.5V.
- **Status LED Ring (WS2812 RGB, 5V):**
  - Driven in SPI mode over `/dev/spidev0.0` (MOSI `GPIO 10` / Pin 19) to avoid PWM/DMA channel conflicts with motors/audio.

---

## 📂 Codebase Structure & Software State

### 1. Robot Control Package (`robot/`)
A Python package managed with `uv` (requires Python 3.11).
- **Fully Implemented off-Pi Modules:**
  - `rag/`: Hungarian offline BM25 retrieval over the Yotengrit corpus. Normalization includes NFKD case-folding/accent stripping and a Hungarian stopword filter. Prepares a structured grounding prompt.
  - `tools/parser.py`: Robust parser for the positional `<tool>NAME v1 v2 ...</tool>` LLM tool-calling grammar (e.g., `move`, `turn`, `stop`, `camera`, `set_speed`, `set_mode`, `request_navigation_help`, `set_oracle`, `scan_wifi`). Features tolerant fail-closed skipping on runtime errors and strict parsing for validation.
  - `health/`: Multi-layered health check system. Triggers safe-mode `/run/freedroid/safe_mode` on critical failures.
- **Phase 4 Hardware Stubs (Pi-only):**
  - `motion/` (Cytron motor controller classes using `lgpio`), `safety/` (ultrasonic polling watchdog thread), `voice/` (openWakeWord, Whisper.cpp STT, Piper TTS), and `orchestrator/` (main async event loop).

### 2. Fine-Tuning Environment (`training/`)
Fine-tuning teaches style, persona, and values (facts belong in the RAG corpus).
- **Base Models:** Llama is the selected family (Llama 3.1 8B in Cloud / Llama 3.2 3B on Edge).
- **Infrastructure:** Google Colab T4 GPU via Unsloth QLoRA with the `--preset gentle` recipe (epochs=1, lr=5e-5, r/alpha=8, dropout=0.05) to prevent overfitting.
- **Dataset (`training/dataset/`):** 726 examples, Alpaca format. Deterministically shuffled and split with a 90/10 ratio (`train.jsonl` (653) / `val.jsonl` (73)) by `merge_and_split.py`. Supports tool expansions and RAG grounding examples.
- **Ollama Modelfile:** Embeds the Llama 3 template, custom `stop` parameters, and the authoritative Hungarian Yotengrit system prompt.
- **Evaluations:** Custom 25-question persona benchmark (`persona_benchmark.json`) scored across 6 dimensions on the `ertekelo_sablon.md` rubric.

---

## 🛠️ Developer Workflows & Commands

### Infrastructure Management (Terraform)
```bash
cd infra/terraform
terraform init          # remote S3 backend ("terraform-s3-access" profile)
terraform fmt -recursive
terraform plan
terraform apply         # provisions CAX31 and runs Ansible site.yml on the cloud
terraform apply -var cloud_server_type=cax41   # provisions a larger CAX41 instance
terraform destroy       # tears down cloud server only; Pi is untouched
```

### Configuration Provisioning (Ansible)
```bash
cd infra/ansible
ansible-playbook --syntax-check -i inventory.ini site.yml
ansible-playbook -i inventory.ini site.yml
ansible-playbook -i inventory.ini site.yml --limit cloud
ansible-playbook -i inventory.ini site.yml -e edge_ollama_model=llama3.2:3b
```

### Robot Development & Local Testing (`robot/`)
```bash
cd robot
uv sync --extra dev     # sync dependencies and create virtual environment
uv run pytest           # run unit tests (pure-python tests pass off-Pi; hardware-tests xfail/skip)
uv run pytest -m phase4 # run the TDD harness
uv run ruff check .     # run code quality linter
uv run freedroid-health # run a local diagnostic check
```

### Dataset Processing & Benchmarking (`training/`)
```bash
# Merge staging files and regenerate train/val split
cd training/dataset
python3 merge_and_split.py          # dry-run stats
python3 merge_and_split.py --write  # execute merge and write splits

# Run the 25-question persona benchmark against local Ollama models
cd training
python3 run_benchmark.py --models szabi-llama szabi-qwen --json-out
```

---

## 🔒 Security & Safety Invariants
1. **Network Safety:** `scan_wifi()` is strictly read-only and parses SSID/Signal/Security. The robot **never** connects to or configures Wi-Fi networks from LLM commands.
2. **Watchdog Supremacy:** The ultrasonic safety watchdog is fully decoupled from the LLM thread. Immediate `stop()` is issued on hardware once any sensor detects an obstacle under `25.0 cm` (configurable threshold), overriding any model actions.
3. **No Local Fine-tuning:** Training only occurs in the Google Colab sandbox or similar remote environments.
4. **Credential Isolation:** Never commit secrets. All API tokens and hcloud keys belong in `.tfvars` or `.env` files, which are git-ignored.
