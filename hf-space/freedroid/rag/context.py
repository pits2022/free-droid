"""Assemble retrieved chunks into a grounding preamble for the LLM prompt.

The fine-tuned persona lives in the Ollama Modelfile SYSTEM prompt; here we only
prepend the retrieved source so the model answers FROM it — and, on no retrieval,
hand the bare query through so the persona's own "nincs rá biztos adatom" kicks in.
"""
from __future__ import annotations

from collections.abc import Sequence

from freedroid.rag.retriever import Hit

_INSTRUCTION = (
    "Az alábbi forrás alapján válaszolj. Ha a válasz nincs benne, "
    "mondd ki őszintén, hogy erről nincs biztos tudásod."
)


def build_context(hits: Sequence[Hit]) -> str:
    """The retrieved chunks as a plain, self-contained source block."""
    return "\n\n".join(f"[{h.chunk.title}]\n{h.chunk.text}" for h in hits)


def build_prompt(query: str, hits: Sequence[Hit]) -> str:
    """Grounding prompt: source + instruction + question. Bare query if no hits."""
    if not hits:
        return query
    return f"[FORRÁS]\n{build_context(hits)}\n[/FORRÁS]\n\n{_INSTRUCTION}\n\nKérdés: {query}"
