---
title: Szabi Free-Droid Chat
emoji: 🤖
colorFrom: red
colorTo: green
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
hardware: zero-a10g
models:
  - unsloth/Meta-Llama-3.1-8B-Instruct
  - jabba77/Szabi-Llama-v7
short_description: Csevegj Szabival — szuverén magyar AI-robot (Llama 8B v7)
---

# 🤖 Szabi — Free-Droid chat (Llama 3.1 8B v7)

Chat with **Szabi**, a sovereign, open-source, **Hungarian-only** AI robot persona, fine-tuned from
**Llama 3.1 8B** (Built with Llama). This Space runs the demo-faithful stack:

- **Persona** from the v7 LoRA adapter ([`jabba77/Szabi-Llama-v7`](https://huggingface.co/jabba77/Szabi-Llama-v7)).
- **Facts** from an offline **BM25 RAG** over the Yotengrit corpus (bundled) — not baked into the weights.
- **Hungarian-only** enforced in code by a deterministic `language_guard` (Szabi replies in Hungarian even
  if you ask for another language — try it).

Motion commands produce a positional `<tool>…</tool>` call (e.g. `<tool>move forward 2</tool>`). Runs on
**ZeroGPU** (requires a PRO account for the Space owner; otherwise falls back to CPU and is slow).

> ⓘ Conversations are logged (to a private dataset) for testing. Don't enter personal or sensitive data.

**License:** model weights under the **Llama Community License** + Acceptable Use Policy; app code GPL-3.0.
