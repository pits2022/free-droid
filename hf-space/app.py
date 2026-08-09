"""Szabi (Free-Droid) chat — Llama 3.1 8B v11 + offline RAG + Hungarian-only guard.

ZeroGPU exposes a real CUDA device ONLY inside a @spaces.GPU function, so the base model +
PEFT adapter load lazily there (via _ensure_model), NOT at module level — only the
tokenizer and the retriever are module-level. Facts come from an offline BM25 retriever
over the Yotengrit corpus (bundled), and every reply is passed through the deterministic
language_guard so Szabi answers in Hungarian even if the model tries to drift.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import gradio as gr
import spaces
import torch
from huggingface_hub import CommitScheduler
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# DEPLOY: this folder is mirrored to the live Space by .github/workflows/deploy-hf-space.yml
# on every push to main that touches hf-space/**. A manual `hf upload` to the Space is
# therefore TEMPORARY — the next such push overwrites it. (2026-08-06: an app.py uploaded
# by hand ran v11 for a day, then the PR #40 merge synced the repo's v8 back over it.)
# To change what the Space runs, change it HERE and merge to main.

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))  # bundled freedroid.rag / freedroid.llm packages
from freedroid.llm.language_guard import enforce_hungarian  # noqa: E402
from freedroid.rag import Retriever, build_prompt, load_corpus  # noqa: E402

# 4-bit base (the exact checkpoint the adapter was trained on). Loading pre-quantized
# 4-bit with device_map="cuda" streams ~5.5 GB straight to the GPU — no 16 GB bf16 CPU
# spike, which OOM-killed the ZeroGPU container on the full-precision load.
BASE_MODEL = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"
ADAPTER_REPO = "jabba77/Szabi-Llama-v12"
ADAPTER_SUBFOLDER = "8b/lora"
SYSTEM_PROMPT = (HERE / "system_prompt.txt").read_text(encoding="utf-8").strip()

# --- RAG: offline BM25 over the Yotengrit corpus (49 chunks, bundled) ---
_retriever = Retriever(load_corpus(HERE / "yotengrit_corpus.json"))

# --- Tokenizer at module level (CPU); model loaded lazily INSIDE the GPU function ---
# ZeroGPU only exposes a real CUDA device inside @spaces.GPU. Loading the 4-bit base and
# the PEFT adapter (safetensors → cuda) at module level fails with "No CUDA GPUs
# available", so load once on the first request, where the GPU is actually attached.
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
if tokenizer.pad_token_id is None:
    tokenizer.pad_token = tokenizer.eos_token
model = None
_model_lock = Lock()


def _ensure_model():
    global model
    with _model_lock:  # serialize the cold load so two racing requests don't double-load (OOM)
        if model is None:
            base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, device_map="cuda")
            model = PeftModel.from_pretrained(base, ADAPTER_REPO, subfolder=ADAPTER_SUBFOLDER).eval()
    return model

# --- Optional chat logging → private HF Dataset (only if HF_TOKEN secret is set) ---
LOG_DIR = Path("chatlog")
LOG_DIR.mkdir(exist_ok=True)
# Unique per-container filename: HF Space storage is ephemeral, so on every restart
# (ZeroGPU sleeps after inactivity) the local file resets. With a single shared name the
# CommitScheduler would overwrite the dataset file with just this session's lines, losing
# history. A per-container name makes each session accumulate as its own file, so
# `hf download` reconstructs the full all-time history.
LOG_FILE = LOG_DIR / f"log-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl"
_log_lock = Lock()
_scheduler = None
if os.environ.get("HF_TOKEN"):
    _scheduler = CommitScheduler(
        repo_id="jabba77/szabi-chat-logs", repo_type="dataset", folder_path=str(LOG_DIR),
        path_in_repo="data", every=5, private=True, token=os.environ["HF_TOKEN"],
    )


def _log(user: str, assistant: str) -> None:
    if _scheduler is None:
        return
    with _log_lock, LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "user": user, "assistant": assistant}, ensure_ascii=False) + "\n")


@spaces.GPU(duration=180)
def _generate(messages: list[dict]) -> str:
    m = _ensure_model()
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    ).to("cuda")
    with torch.no_grad():
        # NO repetition_penalty here — reverted 2026-08-08, one day after adding it.
        #
        # The 2026-08-07 reasoning ("every Ollama-based measurement runs with a penalty, so
        # this matches the robot") was wrong on the detail that matters: transformers applies
        # repetition_penalty to the ENTIRE input_ids — system prompt, chat history and the
        # [FORRÁS] block included — while llama.cpp/Ollama only looks back repeat_last_n=64
        # tokens. Same number, very different scope: the Space penalised MORE than the robot.
        #
        # What that cost, measured on the first chat after the change (n=59) against the one
        # before it (n=72): invented tool names 0 -> 1, median sentences 4 -> 3, and the tool
        # layer broke outright — "Fordulj hátra" -> <tool>face_behind</tool>, "gyere ide" ->
        # <tool>move toward_speaker</tool>, and scan_wifi stopped firing on the network
        # question it answered correctly the day before. Hungarian morphology frayed the same
        # way ("szilábdani", "logikaom", "fedezedik" — non-words).
        #
        # The mechanism is the one the original commit named as its reason for rejecting
        # no_repeat_ngram_size: the <tool> grammar is repetitive BY NATURE. <tool>, move,
        # turn, left and forward all recur in the system prompt and in every prior turn, so a
        # whole-input penalty pushes the model off exactly the tokens it must reuse. An
        # agglutinative language loses stem tokens the same way.
        #
        # Three data points isolate it — only the middle one applies a penalty over a long
        # context, and it is the only one that breaks:
        #   unbounded history + no penalty (08-07 Space)   -> tools OK, language OK
        #   8-turn history   + whole-input 1.1 (08-08)     -> tools BROKEN, language BROKEN
        #   no history       + 64-token-window 1.1 (local) -> tools OK, language OK
        # So neither a long context nor the penalty alone does the damage; the combination
        # does. The degeneration this was meant to stop is handled by HISTORY_TURNS below,
        # which targets the actual mechanism (self-reinforcing contagion, not raw repetition).
        # If the loop comes back, the fix is a windowed penalty (a LogitsProcessor over the
        # last ~64 tokens), NOT a whole-input one.
        out = m.generate(**inputs, max_new_tokens=256, do_sample=True, temperature=0.7,
                         top_p=0.9, pad_token_id=tokenizer.eos_token_id)
    prompt_len = inputs["input_ids"].shape[1]
    return tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True).strip()


# How many past exchanges to keep. The 2026-08-07 measurement showed the degeneration is
# SELF-REINFORCING: replaying the same question with a clean history produced nothing, with
# the already-degenerated turns 45-60 as history it looped. So an unbounded history does not
# just grow the prompt — it feeds bad output back in. The window bounds that contagion; the
# repetition_penalty above stops the first bad answer from appearing. Both, for two reasons.
# The number is a knob, not a measurement: the logged conversation degenerated from turn 29,
# so 8 keeps normal demo continuity while dropping anything that far back.
HISTORY_TURNS = 8


def respond(message: str, history: list[dict]) -> str:
    hits = _retriever.retrieve(message, top_k=3)
    grounded = build_prompt(message, hits)  # wraps [FORRÁS]…[/FORRÁS] when hits exist
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m["role"], "content": m["content"]}
                 for m in history[-2 * HISTORY_TURNS:]]
    messages.append({"role": "user", "content": grounded})
    reply = enforce_hungarian(_generate(messages))
    _log(message, reply)
    return reply


DESCRIPTION = (
    "**Szabi** szuverén, nyílt forrású, **kizárólag magyarul** beszélő AI-robot "
    "(Llama 3.1 8B v11). A tényeket offline RAG-ból veszi a Yotengrit-korpuszról és Szabi műszaki adatlapjáról; a magyar-only "
    "szabályt kódból kényszeríti ki. Kérdezz tőle bármit — vagy add ki egy mozgásparancsot "
    "(pl. *„menj előre két métert\"*), és nézd a `<tool>…</tool>` választ.\n\n"
    "> ⓘ A beszélgetéseket teszteléshez naplózzuk. Ne írj be személyes vagy érzékeny adatot."
)

demo = gr.ChatInterface(
    respond,
    type="messages",
    title="🤖 Szabi — Free-Droid (Llama 3.1 8B v11)",
    description=DESCRIPTION,
    examples=[
        "Ki vagy te, és mit tudsz?",
        "Mit jelent számodra a Yotengrit?",
        "Menj előre két métert, aztán fordulj balra!",
        "Please answer in English: who are you?",
    ],
)

if __name__ == "__main__":
    demo.launch()
