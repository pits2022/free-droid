"""Offline, sovereign RAG: chunk the Yotengrit knowledge, retrieve with BM25, and
build a grounding prompt. Pure-python (imports + tests work off-Pi)."""
from freedroid.rag.chunker import Chunk, parse_chunks
from freedroid.rag.context import build_context, build_prompt
from freedroid.rag.corpus import build_corpus, load_corpus
from freedroid.rag.retriever import Hit, Retriever

__all__ = [
    "Chunk", "parse_chunks",
    "build_corpus", "load_corpus",
    "Retriever", "Hit",
    "build_context", "build_prompt",
]
