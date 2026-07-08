"""Szabi (Free-Droid) chat — Llama 3.1 8B v7 + offline RAG + Hungarian-only guard.

ZeroGPU: the base model + PEFT adapter are placed on CUDA at module level; generation
runs inside a @spaces.GPU function. Facts come from an offline BM25 retriever over the
Yotengrit corpus (bundled), and every reply is passed through the deterministic
language_guard so Szabi answers in Hungarian even if the model tries to drift.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import gradio as gr
import spaces
import torch
from huggingface_hub import CommitScheduler
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))  # bundled freedroid.rag / freedroid.llm packages
from freedroid.llm.language_guard import enforce_hungarian  # noqa: E402
from freedroid.rag import Retriever, build_prompt, load_corpus  # noqa: E402

# 4-bit base (the exact checkpoint the adapter was trained on). Loading pre-quantized
# 4-bit with device_map="cuda" streams ~5.5 GB straight to the GPU — no 16 GB bf16 CPU
# spike, which OOM-killed the ZeroGPU container on the full-precision load.
BASE_MODEL = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"
ADAPTER_REPO = "jabba77/Szabi-Llama-v7"                    # the v7 fine-tune (this repo's sibling)
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


def _ensure_model():
    global model
    if model is None:
        base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, device_map="cuda")
        model = PeftModel.from_pretrained(base, ADAPTER_REPO, subfolder=ADAPTER_SUBFOLDER).eval()
    return model

# --- Optional chat logging → private HF Dataset (only if HF_TOKEN secret is set) ---
LOG_DIR = Path("chatlog")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "log.jsonl"
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
        out = m.generate(**inputs, max_new_tokens=256, do_sample=True, temperature=0.7,
                         top_p=0.9, pad_token_id=tokenizer.eos_token_id)
    prompt_len = inputs["input_ids"].shape[1]
    return tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True).strip()


def respond(message: str, history: list[dict]) -> str:
    hits = _retriever.retrieve(message, top_k=3)
    grounded = build_prompt(message, hits)  # wraps [FORRÁS]…[/FORRÁS] when hits exist
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": grounded})
    reply = enforce_hungarian(_generate(messages))
    _log(message, reply)
    return reply


DESCRIPTION = (
    "**Szabi** szuverén, nyílt forrású, **kizárólag magyarul** beszélő AI-robot "
    "(Llama 3.1 8B v7). A tényeket offline RAG-ból veszi a Yotengrit-korpuszról; a magyar-only "
    "szabályt kódból kényszeríti ki. Kérdezz tőle bármit — vagy add ki egy mozgásparancsot "
    "(pl. *„menj előre két métert\"*), és nézd a `<tool>…</tool>` választ.\n\n"
    "> ⓘ A beszélgetéseket teszteléshez naplózzuk. Ne írj be személyes vagy érzékeny adatot."
)

demo = gr.ChatInterface(
    respond,
    type="messages",
    title="🤖 Szabi — Free-Droid (Llama 3.1 8B v7)",
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
