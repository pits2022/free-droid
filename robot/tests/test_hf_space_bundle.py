"""A HF Space bundle nem sodródhat el a repótól.

A `hf-space/` mappa a Space-re deployolt, ÖNÁLLÓ másolat: a `freedroid` csomag egy
részét és a RAG-korpuszt kézzel visszük át, mert a Space nem a `robot/` projektet
telepíti. Kézi másolás = néma sodródás, és ez már meg is történt: a 2026-07-28-i
kör után a Space a 67 chunkos korpuszt a RÉGI, tövezés nélküli normalizerrel olvasta
volna, azaz a műszaki kérdésekre nem talált volna forrást — a hiba pedig sehol nem
jelzett volna, csak rosszabb válaszokban.

Ez a teszt a másolást nem automatizálja (a Space bundle szándékosan kevesebb modult
tartalmaz, mint a `robot/`), csak azt köti ki, hogy AMI át van másolva, az azonos legyen.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# robot/tests/test_hf_space_bundle.py -> parents[2] = repo root
_ROOT = Path(__file__).resolve().parents[2]
_SPACE = _ROOT / "hf-space"
_SRC = _ROOT / "robot" / "src" / "freedroid"

# Minden modul, amit a Space bundle átvesz a robot/ csomagból.
BUNDLED = [
    "rag/__init__.py", "rag/normalize.py", "rag/retriever.py", "rag/chunker.py",
    "rag/corpus.py", "rag/context.py", "llm/language_guard.py",
]


@pytest.mark.parametrize("rel", BUNDLED)
def test_bundled_module_matches_source(rel: str):
    bundled, source = _SPACE / "freedroid" / rel, _SRC / rel
    assert bundled.exists(), f"a Space bundle-ből hiányzik: {rel}"
    assert bundled.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"), (
        f"a Space bundle elsodródott: hf-space/freedroid/{rel} != robot/src/freedroid/{rel} "
        f"— másold át, különben a Space más kóddal fut, mint amit tesztelünk")


def test_bundled_corpus_matches_repo():
    """A Space a becsomagolt korpusz-JSON-t tölti be, nem építi — az is sodródhat."""
    bundled = json.loads((_SPACE / "yotengrit_corpus.json").read_text(encoding="utf-8"))
    repo = json.loads((_ROOT / "training" / "rag" / "yotengrit_corpus.json").read_text(encoding="utf-8"))
    assert bundled == repo, (
        f"a Space korpusza {len(bundled)} chunk, a repóé {len(repo)} — másold át")


def test_bundled_system_prompt_matches_canonical():
    """A Space futásidejű promptja == a kanonikus (8B) prompt, amivel a modell tanult."""
    bundled = (_SPACE / "system_prompt.txt").read_text(encoding="utf-8").strip()
    canonical = (_ROOT / "training" / "system_prompt.txt").read_text(encoding="utf-8").strip()
    assert bundled == canonical, "a Space rendszerpromptja elsodródott a kanonikustól"
