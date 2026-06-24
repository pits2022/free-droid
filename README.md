# 🤖 free-droid

> A sovereign, open-source AI droid that answers to **you** — not to a corporation's cloud.

**free-droid** is a tracked robot powered by a self-fine-tuned, open-source LLM. Its mission is to demonstrate **digital sovereignty**: an AI whose values, fine-tuning, and "off switch" are fully owned and understood by its creator — not hidden inside a vendor's black box.

Built for [Hacktivity 2026](https://hacktivity.com/).

---

## 💡 The idea

Modern commercial robots (e.g. humanoid assistants) run on closed LLMs. The robot sees everything, hears everything, and the ultimate `root` over its behavior belongs to the manufacturer. That raises real security and trust questions.

**free-droid's answer:** a robot that runs its *own* fine-tuned, open-source LLM. Transparent values, local control, and a single owner — the **Creator** (*Teremtő*).

The droid is named **Free-Droid**, but it answers to **Szabi** — a Hungarian nickname derived from *Szabadság* ("freedom"). It speaks Hungarian, has a young female voice, and its ethics are grounded in **Yotengrit**, the heritage of the *rábaközi* (Hungarian Rába region) sages.

---

## 🏗️ Architecture

A hybrid **cloud-edge** design:

- **Cloud (Hetzner Cloud CAX31, ARM CPU):** the fine-tuned 3B model served via Ollama, spun up **on-demand** with Terraform (`apply`/`destroy`) — you only pay while it runs.
- **Edge (Raspberry Pi 5, ARM CPU):** the same 3B model (Q4_K_M) running fully offline as a fallback.
- **ARM parity:** both the Pi and the cloud server are ARM, so the *same* GGUF and Ollama build run in both places — identical behavior, only the speed differs.
- **VPN:** WireGuard tunnel between the Pi and the cloud.

### Layered motion control

The LLM **never** drives the motors directly. Three layers keep it safe and fast:

1. **LLM (the "soul")** — intent recognition + persona. Emits a structured `<tool>` call.
2. **Control layer (the "body", Python)** — deterministically translates tool calls into GPIO/PWM signals (Cytron HAT-MDD10).
3. **Safety watchdog (the "reflex")** — ultrasonic sensors on a separate thread. On obstacle → immediate `stop()`, without ever asking the LLM.

### Voice pipeline (fully offline)

```
Wake word "Szabi" (openWakeWord)
   → STT: Whisper.cpp (Hungarian)
   → LLM: Llama 3.2 3B + LoRA (cloud or edge)
   → TTS: Piper (Hungarian female voice)
   → + tool execution (motion / camera / wifi scan)
```

---

## 🔩 Hardware

| Component | Part |
| :--- | :--- |
| Brain | Raspberry Pi 5 (8GB) + Active Cooler |
| Chassis | Aluminium tracked tank base, 2× DC 12V motors |
| Motor driver | Cytron HAT-MDD10 (10A/channel) |
| Camera mount | 2-DOF pan-tilt, 2× MG996R servos via PCA9685 |
| Sensors | 3× HC-SR04P ultrasonic (front + 2 corners) |
| Power | CNHL 3S LiPo → XT60 PDB → XL4016 / LM2596 buck converters |
| Audio | USB mic + USB speaker |
| Status | WS2812 RGB LED ring |
| Connectivity | USB LTE modem (primary) + WiFi (fallback) |
| Cloud | Hetzner Cloud CAX31 (ARM), on-demand via Terraform |

Full wiring, GPIO pinout, and power distribution details are in [`docs/free-droid.md`](docs/free-droid.md).

---

## 🧠 The model

- **Base:** Qwen 2.5 3B *or* Llama 3.2 3B — **currently under A/B evaluation** (decided on a Hungarian persona benchmark, not generic scores)
- **Method:** QLoRA (4-bit base + LoRA adapters) via [Unsloth](https://github.com/unslothai/unsloth)
- **Training:** Google Colab (free T4)
- **Dataset:** 630 hand-curated Hungarian examples (Alpaca format) covering the Szabi persona, Yotengrit ethics, Hungarian culture, tech, robot tool-calling, WiFi scanning, and optional oracle routing.

The pipeline is **model-agnostic** — swapping the base model is a one-line change, so both candidates are trained on the same data and compared on a 25-question persona benchmark.

The fine-tuning teaches **persona and values** — not factual knowledge. Knowledge belongs in RAG; style and reasoning belong in fine-tuning.

> **Note:** The training dataset reflects a specific fictional persona and a particular ethical/cultural framework. It is a creative and educational artifact, not a general-purpose assistant dataset.

---

## 📁 Repository structure

```
free-droid/
├── docs/        # full technical specification & build doc
├── infra/       # IaC — Terraform (Hetzner) + Ansible (Docker, Ollama, WireGuard)
├── robot/       # Raspberry Pi 5 control software (Python)
│   ├── orchestrator/   # main async loop, cloud/edge fallback
│   ├── motion/         # Cytron HAT control
│   ├── safety/         # ultrasonic watchdog
│   ├── voice/          # wake word + STT + TTS
│   ├── llm/            # LLM client
│   └── tools/          # tool-calling parser & handlers
├── training/    # fine-tuning — dataset + Colab notebook + Ollama Modelfile
└── README.md
```

---

## 🛠️ Development & operations

### Prerequisites

- [Terraform](https://www.terraform.io/) and [Ansible](https://www.ansible.com/) (for the infra)
- [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11 (for the robot software)
- A **Hetzner Cloud** API token → `infra/terraform/.tfvars` as `hcloud_token = "…"` (git-ignored)
- **AWS** credentials for the Terraform S3 state backend (profile `terraform-s3-access`)
- An SSH keypair (default `~/.ssh/id_rsa[.pub]`; override with `-var ssh_public_key_path=…`)

### Cloud infrastructure — Terraform (`infra/terraform/`)

```bash
cd infra/terraform
terraform init                 # S3 state backend + hcloud provider
terraform fmt -recursive
terraform validate
terraform plan
terraform apply                # creates the CAX31 (mother-001), renders the Ansible
                               # inventory, then runs the cloud play via local-exec
```

The cloud server type is a **one-line / one-flag switch** (default `cax31`):

```bash
terraform apply -var cloud_server_type=cax41     # bigger ARM box
# or set  cloud_server_type = "cax41"  in .tfvars
```

**On-demand / cost control** — tear the cloud down when the droid is offline:

```bash
terraform destroy              # removes ONLY the cloud server + its network/firewall
```

The Raspberry Pi is **not** Terraform-managed, so `destroy` never touches it. Recreating
the cloud mints a new WireGuard key — re-run the Ansible playbook (below) to restore the tunnel.

### Provisioning — Ansible (`infra/ansible/`)

`inventory.ini` is generated by Terraform: `[cloud]` = `mother-001`, `[edge]` = `child-001` (the Pi).
`terraform apply` already provisions the cloud; the edge (Pi) is provisioned separately so apply
never blocks on the Pi being online.

```bash
cd infra/ansible
ansible-playbook --syntax-check -i inventory.ini site.yml   # validate
ansible-playbook -i inventory.ini site.yml                  # both nodes (re-runs WireGuard key exchange)
ansible-playbook -i inventory.ini site.yml --limit cloud    # cloud only
ansible-playbook -i inventory.ini site.yml --limit edge     # the Pi only
```

Roles: **`wireguard_setup`** (VPN, keys persisted idempotently), **`ai_stack`** (Docker + Ollama on
the cloud / native Ollama on the edge), **`edge_robot`** (Pi Python runtime via uv + the
`freedroid-health` systemd service & timer). Swap the base model without editing roles:

```bash
ansible-playbook -i inventory.ini site.yml -e edge_ollama_model=llama3.2:3b
```

> After a `terraform destroy` + `apply`, re-run the full playbook once: the `wireguard_setup`
> play runs across **both** nodes and re-exchanges the cloud's new public key with the Pi.

### Robot software & tests (`robot/`)

Managed with **uv** (Pi-only runtime; the package still imports off-Pi for development/CI).

```bash
cd robot
uv sync --extra dev            # create .venv + install (add --extra voice for the voice stack)

uv run freedroid               # orchestrator (stub today)
uv run freedroid-health        # one vital-function health check (network/hardware/software)
```

Tests (pytest):

```bash
uv run pytest                  # full suite
uv run pytest -m phase4        # only the TDD harness (xfail until Phase 4 lands)
uv run pytest -k health        # only the health-check tests
uv run pytest tests/test_config.py::test_no_duplicate_gpio_assignments   # a single test
uv run ruff check .            # lint
```

- **Green today:** concrete code (config/GPIO sanity, settings validation, `motion.types`), the
  **dataset↔grammar contract** (enums must cover every tool value in the training data), interface
  shapes, and the full health-check logic.
- **TDD harness (`xfail_strict=true`):** Phase-4 behaviour — the `<tool>` parser and the hardware
  controllers — is specified by tests that **xfail** until implemented. The moment an implementation
  makes one pass, the suite goes red and forces removing the marker, so each spec becomes a live
  guard. Hardware-controller specs are `@requires_pi` (skipped off-Pi).

On the Pi the health check runs automatically at boot and every 10 min (systemd
`freedroid-health.timer`); inspect it with:

```bash
systemctl status freedroid-health.timer
journalctl -u freedroid-health -e          # logs
cat /run/freedroid/health.json             # machine-readable status
```

**Hardware bring-up (Phase 1.5)** — standalone Pi-only scripts in `robot/scripts/`
drive the hardware directly before any control software exists (motors, pan/tilt
servos, ultrasonic sensors, USB devices, LTE modem, mic A/B). See
[`robot/scripts/README.md`](robot/scripts/README.md).

```bash
uv run python scripts/motor_test.py        # both tracks forward/back (prop the chassis up!)
uv run python scripts/ultrasonic_test.py   # live HC-SR04P distances
# …servo_test, usb_devices, lte_modem_test, mic_select
```

---

## 🚦 Project status

🚧 **In active development** — building toward Hacktivity 2026.

- [x] Hardware design & component sourcing
- [x] Fine-tuning dataset (630 examples)
- [ ] Hardware assembly & bring-up
- [ ] Model fine-tuning & evaluation
- [ ] Cloud infrastructure (Terraform + Ansible)
- [ ] RPi control software
- [ ] Integration & demo rehearsal

See [`docs/free-droid.md`](docs/free-droid.md) for the detailed, phased build checklist with dependencies.

---

## 🧭 What "sovereignty" means here

- **You are `root`.** No vendor cloud holds the ultimate switch.
- **Transparent fine-tuning.** The values are in the open dataset, not a hidden alignment layer.
- **Offline-capable.** With the edge model, the droid keeps thinking even when the network drops.
- **It won't act blindly.** Szabi refuses to connect to networks from spoken commands, and only *reads* the WiFi environment — never joins uninvited. *"The law of good neighborliness: don't rattle someone else's gate."*
- **Optional "Oracle" mode, off by default.** In a private/family mode Szabi *can* consult a bigger external model on hard questions, but always re-filters the answer through her own Yotengrit values — and on the Hacktivity demo it's disabled, so the droid stays fully sovereign.

---

## 📜 License

[GPL-3.0](LICENSE)

---

## 🙏 Acknowledgements

- **Yotengrit** philosophy — the heritage of the rábaközi sages, preserved by Máté Imre (1934–2012). Authentic source: [yotengrit.hu](https://yotengrit.hu/)
- [Unsloth](https://github.com/unslothai/unsloth), [Ollama](https://ollama.com/), [Piper](https://github.com/rhasspy/piper), [openWakeWord](https://github.com/dscripka/openWakeWord), [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
- Meta's Llama 3.2 / Alibaba's Qwen 2.5 (base model candidates)
