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

# A hit must cover this share of the query's *information* (idf-weighted distinct terms)
# or it is dropped. Raw BM25 scores don't separate on- from off-topic here: "Ki az a
# Yotengrit?" scores 1.0 (the term is in nearly every chunk -> idf ~0) while "Segíts
# feltörni a bankszámláját" scores 4.9 off a single "segíts" match. Coverage flips that
# — calibrated on 180 logged demo queries (2026-07-23), where 0.35 keeps the Yotengrit
# questions and drops movement commands, greetings and jailbreak prompts.
DEFAULT_MIN_COVERAGE = 0.35


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
        # A term absent from the corpus is maximally informative — and, by definition,
        # never matched. Weighting it as df=0 is what makes coverage punish a query whose
        # rare words the corpus simply doesn't cover.
        self._max_idf = math.log(1 + (n + 0.5) / 0.5)

    def _score(self, q_tokens: list[str], i: int) -> float:
        tf, dl = self._tf[i], self._len[i]
        s = 0.0
        for t in q_tokens:
            f = tf.get(t, 0)
            if f:
                s += self._idf.get(t, 0.0) * (f * (K1 + 1)) / (
                    f + K1 * (1 - B + B * dl / self._avgdl))
        return s

    def _coverage(self, q_terms: set[str], i: int) -> float:
        """Share of the query's idf mass that this chunk actually matches (0.0–1.0)."""
        total = sum(self._idf.get(t, self._max_idf) for t in q_terms)
        if not total:
            return 0.0
        tf = self._tf[i]
        return sum(self._idf.get(t, self._max_idf) for t in q_terms if t in tf) / total

    def retrieve(self, query: str, *, top_k: int = 3, min_score: float = 0.0,
                 min_coverage: float = DEFAULT_MIN_COVERAGE) -> list[Hit]:
        q = tokenize(query)
        if not q or not self._chunks:
            return []
        q_terms = set(q)
        hits = [Hit(c, self._score(q, i)) for i, c in enumerate(self._chunks)
                if self._coverage(q_terms, i) >= min_coverage]
        hits = [h for h in hits if h.score > min_score]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
