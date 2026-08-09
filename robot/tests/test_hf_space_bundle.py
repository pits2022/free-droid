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
import re
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


def test_space_readme_advertises_the_adapter_it_actually_loads():
    """A Space KÁRTYÁJA ugyanazt a modellt hirdesse, amit az app.py betölt.

    2026-08-09-én az `app.py` már a v12 adaptert töltötte, a Gradio-cím v11-et írt ki,
    a README front mattere pedig v8-at hirdetett — a HF API `cardData.models`-a innen
    veszi az adatot, tehát a Space nyilvános oldala HÁROM különböző verziót állított.
    A címke az app.py-ban azóta az `ADAPTER_REPO`-ból SZÁRMAZIK, de a README statikus
    YAML, azt nem lehet származtatni: ezért őrzi ez a teszt.
    """
    app = (_SPACE / "app.py").read_text(encoding="utf-8")
    m = re.search(r'^ADAPTER_REPO\s*=\s*"([^"]+)"', app, re.M)
    assert m, "nem találom az ADAPTER_REPO-t az app.py-ban"
    adapter = m.group(1)

    readme = (_SPACE / "README.md").read_text(encoding="utf-8")
    fejlec = readme.split("---", 2)[1]
    assert adapter in fejlec, (
        f"a README front mattere nem a betöltött adaptert ({adapter}) hirdeti — "
        f"a HF Space oldala ebből olvassa a `models` mezőt")

    verzio = adapter.rsplit("-", 1)[-1]
    regi = {v for v in re.findall(r"\bv\d+\b", readme) if v != verzio}
    assert not regi, f"a README még régi verziót említ: {sorted(regi)} (a jelenlegi {verzio})"
