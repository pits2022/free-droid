"""Build/load the chunked corpus JSON — the committed RAG artifact.

Source of truth: training/rag/yotengrit.md. The build step parses it into chunks and
writes training/rag/yotengrit_corpus.json, which the runtime loads (the repo ships to
the Pi via uv/Ansible, so the path is present at runtime). The dataset RAG-glue
category reuses the same chunks.

    python -m freedroid.rag.corpus            # regenerate the artifact from the .md
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from freedroid.rag.chunker import Chunk, parse_chunks

# In the repo this file is robot/src/freedroid/rag/corpus.py, so parents[4] is the root.
# The hf-space/ bundle vendors this package at the app root, where that depth may not
# exist — and this runs at IMPORT time, so a bad index would break Space startup rather
# than fail where it is used. The Space always calls load_corpus() with an explicit path
# (the corpus JSON is bundled next to app.py), so the defaults below are repo-only: fall
# back to something harmless instead of raising. Anything that actually BUILDS the corpus
# runs from the repo, where the real root resolves.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4] if len(_HERE.parents) > 4 else _HERE.parent
_RAG_DIR = _REPO_ROOT / "training" / "rag"

# (markdown source, id prefix). One corpus, several sources — the retriever ranks across
# all of them, and the id prefix says which source a hit came from.
#  - yotengrit.md: the Yotengrit knowledge (facts the fine-tune must NOT teach; it
#    hallucinates names and mangles the "three reeds").
#  - szabi_tech.md: Szabi's own hardware/model/architecture facts. Same reason plus one
#    more — these CHANGE (server type, model version, quantization), and baked into the
#    weights every spec edit would mean a re-train. Source of truth: docs/free-droid.md.
DEFAULT_SOURCES: tuple[tuple[Path, str], ...] = (
    (_RAG_DIR / "yotengrit.md", "yot"),
    (_RAG_DIR / "szabi_tech.md", "tech"),
)
DEFAULT_SRC = DEFAULT_SOURCES[0][0]  # kept for callers that build a single source
DEFAULT_OUT = _RAG_DIR / "yotengrit_corpus.json"


def build_corpus(src: Path | None = None, out: Path = DEFAULT_OUT) -> list[Chunk]:
    """Build the corpus from DEFAULT_SOURCES, or from `src` alone if given."""
    sources = ((Path(src), "yot"),) if src is not None else DEFAULT_SOURCES
    chunks: list[Chunk] = []
    for path, prefix in sources:
        chunks += parse_chunks(Path(path).read_text(encoding="utf-8"), id_prefix=prefix)
    Path(out).write_text(
        json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return chunks


def load_corpus(path: Path = DEFAULT_OUT) -> list[Chunk]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Chunk(**d) for d in data]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Yotengrit RAG corpus JSON.")
    # No --src => build from ALL of DEFAULT_SOURCES. Passing --src builds that file alone.
    ap.add_argument("--src", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    chunks = build_corpus(args.src, args.out)
    print(f"wrote {len(chunks)} chunks -> {args.out}")


if __name__ == "__main__":
    main()
