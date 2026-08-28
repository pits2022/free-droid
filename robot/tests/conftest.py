"""Shared fixtures and helpers for the freedroid test suite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from freedroid.config.settings import Settings, load_settings
from freedroid.health.probe import is_pi
from freedroid.tools.parser import ParsedTool, parse_tools

IS_PI = is_pi()

# A `scripts/` nem csomag, de számol: a kalibrációs script geometriája pont az a fajta
# képlet, ami csendben rossz értéket ad. Az importálhatóság ára két sor.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# repo root: robot/tests/conftest.py -> parents[2]
_DATASET = Path(__file__).resolve().parents[2] / "training" / "dataset" / "freedroid_full.json"

def load_tool_calls() -> list[ParsedTool]:
    """Every <tool> call in the dataset, parsed via the real parser (single source
    of truth). The contract tests then check those parsed values against the enums."""
    calls: list[ParsedTool] = []
    for ex in json.loads(_DATASET.read_text()):
        # strict: a malformed dataset call raises (naming it) instead of being
        # silently dropped, so bad training data can't drift past the contract.
        calls.extend(parse_tools(ex.get("output", ""), strict=True))
    return calls


@pytest.fixture(scope="session")
def tool_calls() -> list[ParsedTool]:
    return load_tool_calls()


@pytest.fixture
def settings() -> Settings:
    return load_settings()


requires_pi = pytest.mark.skipif(not IS_PI, reason="requires real Raspberry Pi hardware")


@pytest.fixture(autouse=True)
def nincs_valodi_kamera(monkeypatch):
    """Az `Orchestrator` NE építsen valódi pan/tilt kamerát a tesztekben.

    A kamera 2026-08-28-án lett bekötve (`camera=None` -> épít egyet). A fejlesztőgépen
    ez láthatatlan, mert a `board` import elhasal és a tűrő ág `None`-t ad — a Pi-n
    viszont SIKERÜLNE, és a `PanTiltCamera` konstruktora középre hajtja mindkét
    tengelyt. Vagyis a teszt-suite MEGMOZGATNÁ a szervókat, körönként, egy asztalon álló
    roboton. Egy tesztfuttatás ne nyúljon hardverhez, hacsak nem az a tárgya
    (`@requires_pi`).

    Aminek valódi kamera kell, az `monkeypatch`-csel visszaveheti, vagy adjon be sajátot
    az `Orchestrator(camera=...)` paraméterben — az ág érintetlen.
    """
    from freedroid.orchestrator import Orchestrator

    monkeypatch.setattr(Orchestrator, "_kamera", staticmethod(lambda settings: None))
