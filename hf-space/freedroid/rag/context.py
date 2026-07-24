"""Assemble retrieved chunks into a grounding preamble for the LLM prompt.

The fine-tuned persona lives in the Ollama Modelfile SYSTEM prompt; here we only
prepend the retrieved source so the model answers FROM it — and, on no retrieval,
hand the bare query through so the persona's own "nincs rá biztos adatom" kicks in.
"""
from __future__ import annotations

from collections.abc import Sequence

from freedroid.rag.retriever import Hit

# The old wording ("Az alábbi forrás alapján válaszolj. Ha a válasz nincs benne, …") was
# itself the source of the meta-leak: the model paraphrased it straight back as "a válasz
# a forrásban van/nincs" in 6.7% of the logged demo replies. The source block is framed as
# her own knowledge, and naming it is explicitly forbidden.
_INSTRUCTION = (
    "A fenti a te saját tudásod – abból válaszolj, a magad szavaival. "
    "Sose említsd, hogy forrásból, szövegből vagy adatból dolgozol. "
    "Amiről nincs benne semmi, arra csak ennyit mondj: „Ezt nem tudom.”"
)


def build_context(hits: Sequence[Hit]) -> str:
    """The retrieved chunks as a plain, self-contained source block."""
    return "\n\n".join(f"[{h.chunk.title}]\n{h.chunk.text}" for h in hits)


def build_prompt(query: str, hits: Sequence[Hit]) -> str:
    """Grounding prompt: source + instruction + question. Bare query if no hits."""
    if not hits:
        return query
    return f"[FORRÁS]\n{build_context(hits)}\n[/FORRÁS]\n\n{_INSTRUCTION}\n\nKérdés: {query}"
