"""Self-contained Okapi BM25 retriever over the Yotengrit chunks.

No external dependency — sovereign, deterministic, and testable off-Pi. Title tokens
are weighted (`title_boost`) so a question that echoes a heading ranks its chunk first.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from freedroid.rag.chunker import Chunk
from freedroid.rag.normalize import tokenize

K1 = 1.5
B = 0.75


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class Retriever:
    """BM25 index built once over the chunks; query with `retrieve`."""

    def __init__(self, chunks: list[Chunk], *, title_boost: int = 2) -> None:
        self._chunks = list(chunks)
        self._tf: list[Counter[str]] = []
        self._len: list[int] = []
        df: Counter[str] = Counter()
        for c in self._chunks:
            tokens = tokenize(c.text) + tokenize(c.title) * title_boost
            tf = Counter(tokens)
            self._tf.append(tf)
            self._len.append(sum(tf.values()))
            df.update(tf.keys())
        n = len(self._chunks)
        self._avgdl = (sum(self._len) / n) if n else 0.0
        # idf floored at 0 so a term in almost every doc can't push scores negative.
        self._idf = {t: max(0.0, math.log(1 + (n - d + 0.5) / (d + 0.5)))
                     for t, d in df.items()}

    def _score(self, q_tokens: list[str], i: int) -> float:
        tf, dl = self._tf[i], self._len[i]
        s = 0.0
        for t in q_tokens:
            f = tf.get(t, 0)
            if f:
                s += self._idf.get(t, 0.0) * (f * (K1 + 1)) / (
                    f + K1 * (1 - B + B * dl / self._avgdl))
        return s

    def retrieve(self, query: str, *, top_k: int = 3, min_score: float = 0.0) -> list[Hit]:
        q = tokenize(query)
        if not q or not self._chunks:
            return []
        hits = [Hit(c, self._score(q, i)) for i, c in enumerate(self._chunks)]
        hits = [h for h in hits if h.score > min_score]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
