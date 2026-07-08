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

# robot/src/freedroid/rag/corpus.py -> parents[4] = repo root. In a flattened bundle
# (e.g. the HF Space) the file sits shallower, so guard the index — the DEFAULT_* paths
# below are only used by build_corpus / load_corpus's default arg, and the Space always
# passes an explicit corpus path, so a bogus fallback here is never read.
_here = Path(__file__).resolve()
_REPO_ROOT = _here.parents[4] if len(_here.parents) > 4 else _here.parent
DEFAULT_SRC = _REPO_ROOT / "training" / "rag" / "yotengrit.md"
DEFAULT_OUT = _REPO_ROOT / "training" / "rag" / "yotengrit_corpus.json"


def build_corpus(src: Path = DEFAULT_SRC, out: Path = DEFAULT_OUT) -> list[Chunk]:
    chunks = parse_chunks(Path(src).read_text(encoding="utf-8"))
    Path(out).write_text(
        json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return chunks


def load_corpus(path: Path = DEFAULT_OUT) -> list[Chunk]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Chunk(**d) for d in data]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Yotengrit RAG corpus JSON.")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    chunks = build_corpus(args.src, args.out)
    print(f"wrote {len(chunks)} chunks -> {args.out}")


if __name__ == "__main__":
    main()
