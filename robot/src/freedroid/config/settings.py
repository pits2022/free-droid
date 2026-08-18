"""Runtime tunables with sane defaults. Override via env / config file later.

Defaults are validated once at construction (range checks) so an out-of-range
value fails loudly at startup rather than mis-driving a motor silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

# The retriever owns this default: it is bundled standalone (HF Space) without config.
from freedroid.rag.retriever import DEFAULT_MIN_COVERAGE


@dataclass(frozen=True)
class LLMEndpoints:
    # Cloud Ollama is reachable over WireGuard; edge Ollama is loopback-only.
    cloud_url: str = "http://10.0.0.1:11434"
    edge_url: str = "http://127.0.0.1:11434"

    # ASZIMMETRIKUS: a felhő a 8B-t viszi, az edge a 3B-t (spec, 2. szakasz). A NÉV az
    # Ollama tagje a KÉT KÜLÖN gépen — nem ugyanaz a modell két helyen, tehát nem lehet
    # egy mező.
    #
    # ⚠️ Ezek a BÁZISMODELLEK, és szándékosan azonosak azzal, amit az Ansible ténylegesen
    # telepít (`ai_stack/defaults/main.yml`: cloud_ollama_model / edge_ollama_model).
    # A FINOMHANGOLT modell Ollama-tagje (a `training/Modelfile`-ból,
    # `ollama create szabi -f Modelfile`) még nincs kiszállítva — amíg nincs, egy
    # „szabi:..." alapértelmezés itt csak 404-et hozna a valódi Pi-n, és a health check
    # is CRITICAL-t jelentene. A tag cseréje EGY konfigsor lesz, nem kódmódosítás.
    cloud_model: str = "llama3.1:8b"
    edge_model: str = "llama3.2:3b"

    # HÁROM külön időkorlát, és a szétválasztás a lényeg (lásd `llm/__init__.py`):
    # a `probe` dönti el, MELYIK háttér válaszol, a generálási korlátok pedig csak
    # a végső határt adják. Egy közös, rövid korlát a hideg felhőt kizárná.
    probe_timeout_s: float = 2.0
    cloud_timeout_s: float = 60.0
    edge_timeout_s: float = 90.0

    def __post_init__(self) -> None:
        for nev in ("probe_timeout_s", "cloud_timeout_s", "edge_timeout_s"):
            if getattr(self, nev) <= 0:
                raise ValueError(f"{nev} must be > 0")


@dataclass(frozen=True)
class SafetySettings:
    stop_threshold_cm: float = 25.0   # confirmed with Creator
    poll_interval_s: float = 0.05     # watchdog thread cadence
    # Per-sensor overrides, e.g. {"front": 30.0}. Read-only (frozen settings).
    per_sensor_cm: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.stop_threshold_cm <= 0:
            raise ValueError("stop_threshold_cm must be > 0")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")


@dataclass(frozen=True)
class MotionSettings:
    default_speed: float = 0.5      # 0.0–1.0 duty
    pwm_frequency_hz: int = 1000

    # MÉRVE 2026-08-17, padlón, a trimmel együtt: 100 cm-es parancsra a robot 222 cm-t
    # tett meg, tehát a korábbi 30.0-s BECSLÉS a valós sebesség kevesebb mint felét
    # mondta — a robot minden utat több mint kétszer hosszabbra hajtott volna.
    #
    # ⚠️ A szám a TRIMMEL EGYÜTT érvényes (a trim lassítja az egyik oldalt, tehát az
    # átlagsebességet is). Ha a trim változik, ezt újra kell mérni.
    #
    # A duty→sebesség viszonyt LINEÁRISnak vesszük, ami alacsony kitöltésnél nem igaz
    # (holtsáv) — ha a `move 0.5` rendre rövidebb lesz a kelleténél, ott kezdd.
    cm_per_s_at_full: float = 66.6
    # MÉRVE 2026-08-17: a 90.0-s becslés a valós fordulási sebesség HARMADÁT mondta —
    # egy 90 fokos fordulás 2.0 s helyett 0.64 s. Helyben forduláskor a két lánctalp
    # egymással szemben forog, tehát a szögsebesség jóval nagyobb, mint amit az
    # egyenes menetből "arányosítva" várnánk; ezt tényleg meg kellett mérni.
    deg_per_s_at_full: float = 280.0

    # Deadman: távolság nélküli `move` (pl. `move forward until obstacle`) sem futhat
    # örökké. Ha a watchdog szála elhal, ez az utolsó határ, ami leállítja a robotot.
    max_run_s: float = 30.0

    # OLDALANKÉNTI TRIM — a robot NEM megy egyenesen azonos kitöltésen (MÉRVE
    # 2026-08-17: balra húz, ~2 m után a folyosó falának fordul). Ez differenciál-
    # hajtásnál a VÁRT eset, nem hiba: a két motor/hajtómű/lánctalp sosem azonos.
    # Enkóder nincs, tehát nincs visszacsatolás — marad a kimért szorzó.
    #
    # A GYORSABB oldalt LASSÍTSD (szorzó < 1), ne a lassabbat gyorsítsd: teljes
    # kitöltésen már nincs hová gyorsítani, és a trim csendben hatástalan lenne.
    # MÉRVE 2026-08-17: ezekkel az értékekkel a robot 222 cm-t ment EGYENESEN.
    # A jobb oldal a gyorsabb, 8%-kal — mérés: scripts/calibrate_motion.py.
    left_duty_trim: float = 1.0
    right_duty_trim: float = 0.92

    # A két lánctalp KÖZÉPVONALÁNAK távolsága. Csak a trim kiszámításához kell
    # (az oldalirányú elsodródásból ebből jön ki a szögelfordulás).
    # MÉRVE 2026-08-17, mérőszalaggal.
    track_width_cm: float = 21.0

    def _validate_trim(self, name: str, value: float) -> None:
        if not 0.0 < value <= 1.0:
            raise ValueError(f"{name} must be within (0.0, 1.0] — lassítani lehet, "
                             f"gyorsítani nem")

    def __post_init__(self) -> None:
        if not 0.0 <= self.default_speed <= 1.0:
            raise ValueError("default_speed must be in [0.0, 1.0]")
        if self.pwm_frequency_hz <= 0:
            raise ValueError("pwm_frequency_hz must be > 0")
        if self.cm_per_s_at_full <= 0:
            raise ValueError("cm_per_s_at_full must be > 0")
        if self.deg_per_s_at_full <= 0:
            raise ValueError("deg_per_s_at_full must be > 0")
        if self.max_run_s <= 0:
            raise ValueError("max_run_s must be > 0")
        self._validate_trim("left_duty_trim", self.left_duty_trim)
        self._validate_trim("right_duty_trim", self.right_duty_trim)
        if self.track_width_cm <= 0:
            raise ValueError("track_width_cm must be > 0")


@dataclass(frozen=True)
class RAGSettings:
    # Offline BM25 retrieval over the Yotengrit corpus. corpus_path="" -> the loader
    # uses its repo-default (training/rag/yotengrit_corpus.json).
    enabled: bool = True
    corpus_path: str = ""
    top_k: int = 3
    min_score: float = 0.0       # a chunk must score strictly above this to be returned
    title_boost: int = 2         # heading tokens weighted Nx in the BM25 index
    min_coverage: float = DEFAULT_MIN_COVERAGE   # idf-weighted query coverage gate

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be > 0")
        if self.min_score < 0:
            raise ValueError("min_score must be >= 0")
        if self.title_boost < 1:
            raise ValueError("title_boost must be >= 1")
        if not 0.0 <= self.min_coverage <= 1.0:
            raise ValueError("min_coverage must be within 0.0–1.0")


@dataclass(frozen=True)
class Settings:
    llm: LLMEndpoints = field(default_factory=LLMEndpoints)
    safety: SafetySettings = field(default_factory=SafetySettings)
    motion: MotionSettings = field(default_factory=MotionSettings)
    rag: RAGSettings = field(default_factory=RAGSettings)


def load_settings() -> Settings:
    """Return effective settings. Stub: returns defaults until config loading lands."""
    return Settings()
