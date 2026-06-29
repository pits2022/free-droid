"""RAG pipeline: chunker, normalizer, BM25 retriever, prompt builder, corpus I/O.

Pure-python — runs off-Pi. The real Yotengrit markdown is the source of truth; tests
parse it directly so they don't depend on a freshly built artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from freedroid.config.settings import RAGSettings
from freedroid.rag import (
    Chunk,
    Retriever,
    build_context,
    build_corpus,
    build_prompt,
    load_corpus,
    parse_chunks,
)
from freedroid.rag.normalize import tokenize

# robot/tests/test_rag.py -> parents[2] = repo root
MD = Path(__file__).resolve().parents[2] / "training" / "rag" / "yotengrit.md"


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return parse_chunks(MD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def retriever(chunks) -> Retriever:
    return Retriever(chunks)


# --- chunker --------------------------------------------------------------- #
def test_chunker_splits_headings_and_skips_meta():
    md = (
        "# Title\n\nintro text, not a chunk\n\n"
        "## Hogyan töltsd ki\n- instruction bullet, no ### so no chunk\n\n"
        "## 1. Szekció\n\n### Első kérdés?\n\nElső válasz.\n\n"
        "### Üres kérdés?\n\n> _..._\n\n"
        "### Második kérdés?\n\nMásodik válasz, két sorban.\nFolytatás.\n"
    )
    out = parse_chunks(md)
    assert [c.title for c in out] == ["Első kérdés?", "Második kérdés?"]  # empty one skipped
    assert out[0].section == "1. Szekció"
    assert out[0].text == "Első válasz."
    assert out[1].text == "Második válasz, két sorban.\nFolytatás."
    assert {c.id for c in out} == {"yot-000", "yot-001"}  # stable, order-based, unique


def test_chunker_drops_rules_and_trailing_note():
    md = (
        "## 1. S\n\n### Q1?\n\nA1.\n\n---\n\n## 2. T\n\n### Q2?\n\nA2.\n\n"
        "---\n\n*(trailing editor note, not a chunk)*\n"
    )
    out = parse_chunks(md)
    assert [c.title for c in out] == ["Q1?", "Q2?"]
    assert out[0].text == "A1." and out[1].text == "A2."   # no `---` absorbed
    assert all("---" not in c.text and "editor note" not in c.text for c in out)


def test_real_corpus_is_clean(chunks):
    assert len(chunks) > 20
    assert all(c.text.strip() for c in chunks)            # no empty bodies
    assert all("_..._" not in c.text for c in chunks)     # no placeholder leak
    assert all(not c.title.startswith("#") for c in chunks)  # heading markers stripped
    assert len({c.id for c in chunks}) == len(chunks)     # ids unique


# --- normalizer ------------------------------------------------------------ #
def test_tokenize_folds_accents():
    assert tokenize("Gönüz") == ["gonuz"]
    assert tokenize("Ősszellem") == ["osszellem"]


def test_tokenize_drops_stopwords_and_shorts():
    toks = tokenize("Ki az a Teremtő és mi a célja?")
    assert "teremto" in toks and "celja" in toks
    assert "ki" not in toks and "az" not in toks and "es" not in toks


# --- retriever ------------------------------------------------------------- #
@pytest.mark.parametrize("query, expected_kw", [
    ("Kik Ukkó és Gönüz?", "Ukkó és Gönüz"),
    ("Mi az a Büün?", "Büün"),
    ("hogyan lett a gonosz szó?", "Gonosz"),
    ("mi a hetedhét ösvény?", "hetedhét ösvény"),
])
def test_retrieve_ranks_right_chunk_first(retriever, query, expected_kw):
    hits = retriever.retrieve(query, top_k=3)
    assert hits, f"no hit for {query!r}"
    assert expected_kw in hits[0].chunk.title


def test_retrieve_no_match_returns_empty(retriever):
    assert retriever.retrieve("kubernetes deploy pipeline yaml") == []


def test_retrieve_empty_query_returns_empty(retriever):
    assert retriever.retrieve("a az és") == []   # all stopwords


def test_retrieve_respects_top_k(retriever):
    assert len(retriever.retrieve("Yotengrit teremtés", top_k=2)) <= 2


def test_title_boost_changes_ranking(chunks):
    boosted = Retriever(chunks, title_boost=5).retrieve("Büün")
    flat = Retriever(chunks, title_boost=1).retrieve("Büün")
    assert boosted[0].chunk.title.startswith("Mi az a")  # heading match wins with boost
    assert flat  # still returns something without boost


# --- context builder ------------------------------------------------------- #
def test_build_prompt_grounds_on_hits(retriever):
    hits = retriever.retrieve("Kik Ukkó és Gönüz?")
    prompt = build_prompt("Ki Gönüz?", hits)
    assert "[FORRÁS]" in prompt and "Kérdés: Ki Gönüz?" in prompt
    assert hits[0].chunk.text[:20] in prompt


def test_build_prompt_passthrough_without_hits():
    assert build_prompt("Mi a kedvenc színed?", []) == "Mi a kedvenc színed?"


def test_build_context_lists_titles(retriever):
    block = build_context(retriever.retrieve("hetedhét ösvény", top_k=1))
    assert block.startswith("[Mi a hetedhét ösvény?]")


# --- corpus round-trip ----------------------------------------------------- #
def test_corpus_build_load_roundtrip(tmp_path, chunks):
    out = tmp_path / "corpus.json"
    built = build_corpus(src=MD, out=out)
    loaded = load_corpus(out)
    assert built == loaded == chunks
    assert json.loads(out.read_text(encoding="utf-8"))[0].keys() >= {"id", "section", "title", "text"}


def test_committed_corpus_matches_markdown(chunks):
    """Guard against the committed artifact drifting from the source .md (run
    `python -m freedroid.rag.corpus` after editing yotengrit.md)."""
    assert load_corpus() == chunks, "yotengrit_corpus.json is stale — rebuild it"


# --- settings validation --------------------------------------------------- #
@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"min_score": -1.0}, {"title_boost": 0}])
def test_rag_settings_reject_bad_values(kwargs):
    with pytest.raises(ValueError):
        RAGSettings(**kwargs)
