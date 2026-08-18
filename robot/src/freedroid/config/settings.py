"""Futásidejű hangolható értékek, józan alapértelmezésekkel + KÖRNYEZETI FELÜLÍRÁS.

Az alapértelmezéseket a konstruktor egyszer ellenőrzi (tartomány-vizsgálat), tehát egy
rossz érték INDULÁSKOR hangosan bukik, nem egy félrehajtott motorban derül ki.

**Miért van env-felülírás (2026-08-18, a Pi-n mérve).** Enélkül az egyetlen mód, hogy a
roboton bármit átállíts, a FORRÁS szerkesztése volt — és ez pontosan az a hibaosztály,
ami már kétszer harapott: egy lokálisan szerkesztett `settings.py` blokkolta a
`git checkout`-ot, a Pi hetekig egy RÉGI branchen állt, és az esti health-check emiatt
jó okból NÉM ROSSZ dolgot igazolt (a régi `llama3.2:3b` tagot, nem az újat). A tanulság
nem az, hogy jobban kell figyelni, hanem hogy a gép-specifikus értéknek nem a
verziókövetett fájlban a helye.

    FREEDROID_<SZEKCIÓ>_<MEZŐ>=érték

    FREEDROID_LLM_EDGE_MODEL=szabi-3b-v12        # névtér nélküli, helyi példány
    FREEDROID_MOTION_DEG_PER_S_AT_FULL=280.0     # egy újramért kalibráció
    FREEDROID_RAG_TOP_K=1                        # gyorsabb edge-válasz, kevesebb forrás
    FREEDROID_SAFETY_STOP_THRESHOLD_CM=40        # nagyobb terem, több tartalék

A systemd `Environment=` sora ugyanezt adja a szolgáltatásnak, tehát az Ansible egy
hosztonkénti értéket úgy állít be, hogy a munkafa TISZTA marad.

Fájl-alapú configot szándékosan NEM adunk hozzá: a systemd unit és az Ansible is
env-ben gondolkodik, egy második forrás pedig csak azt a kérdést szülné, hogy melyik
nyer.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
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
    # A DEMÓ-MODELLEK (a Teremtő, 2026-08-18), PUBLIKUS ollama.com modellként terjesztve.
    #
    # A NÉV ITT SZÓ SZERINT AZ, AMIT AZ ANSIBLE HÚZ — `ai_stack/defaults/main.yml`.
    # A névtérrel együtt: a `pull` után az `ollama list` `csaba_ajtony/szabi-3b-v12:latest`-et
    # mutat, tehát egy rövidített „szabi-3b-v12" itt 404-et adna. A két fájlnak együtt
    # kell mozognia; a `check_edge_model` pont ezt az eltérést fogja meg.
    #
    # ⚠️ A FEJLESZTŐGÉPEN más a helyzet: ott a modellek helyben, `ollama create`-tel
    # készültek, tehát névtér nélkül állnak (`szabi-8b-v12:latest`). Lokális futtatáshoz
    # ezt a két értéket kell felülírni — nem a kódot javítani.
    cloud_model: str = "csaba_ajtony/szabi-8b-v12"
    edge_model: str = "csaba_ajtony/szabi-3b-v12"

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


# Az env-változók, amiket MÁS modulok olvasnak. Azért kell a lista, hogy az elgépelt
# felülírásokra figyelmeztethessünk anélkül, hogy ezekre is rászólnánk.
_EGYEB_ENV = frozenset({
    "FREEDROID_ASSUME_PI", "FREEDROID_GPIOCHIP", "FREEDROID_HEALTH_STATUS",
    "FREEDROID_SAFE_MODE_FLAG", "FREEDROID_TRANSCRIPT_LOG", "FREEDROID_MOTOR_TEST",
    "FREEDROID_DEBUG",
})

_SZEKCIOK = {"LLM": ("llm", LLMEndpoints), "SAFETY": ("safety", SafetySettings),
             "MOTION": ("motion", MotionSettings), "RAG": ("rag", RAGSettings)}

# Csak skalár mezők írhatók felül. A `per_sensor_cm` (Mapping) szándékosan kimarad:
# egy env-be sűrített dict saját mini-nyelvtant kívánna, és az elgépelése némán
# rossz küszöböt adna — épp azt a hibát, ami ellen ez az egész készült.
_IGAZ = {"1", "true", "yes", "igen", "on"}
_HAMIS = {"0", "false", "no", "nem", "off"}


def _ertek(kulcs: str, nyers: str, tipus: str):
    """Sztring -> a mező típusa. Ismeretlen/rossz érték HANGOS hiba.

    A bool külön eset, és nem kényeskedés: a `bool("hamis")` Pythonban IGAZ. Egy
    `FREEDROID_RAG_ENABLED=hamis` tehát némán BEkapcsolva hagyná a RAG-ot.
    """
    if tipus == "bool":
        kicsi = nyers.strip().lower()
        if kicsi in _IGAZ:
            return True
        if kicsi in _HAMIS:
            return False
        raise ValueError(f"{kulcs}={nyers!r} — logikai értéket vártam "
                         f"({'/'.join(sorted(_IGAZ))} vagy {'/'.join(sorted(_HAMIS))})")
    try:
        return {"str": str, "int": int, "float": float}[tipus](nyers)
    except (KeyError, ValueError) as e:
        raise ValueError(f"{kulcs}={nyers!r} — nem értelmezhető {tipus}-ként") from e


def _tipusnev(annotacio: object) -> str:
    """A mező típusának NEVE, akárhogyan is tárolja a Python az annotációt.

    A `from __future__ import annotations` miatt ma minden annotáció SZTRING, tehát
    `f.type == "float"`. Ha viszont ez az import valaha eltűnik (a PEP 649 óta reális
    takarítás), az annotációk kiértékelt TÍPUSOBJEKTUMOK lesznek, és egy sztring-
    összevetés egyetlen mezőre sem illeszkedne — vagyis MINDEN env-felülírás NÉMÁN
    abbahagyná a működését, és a robot az alapértelmezésekkel futna tovább.

    Pontosan az a csendes sodródás, ami ellen ez a modul készült. (PR #88 review.)
    A `test_a_felismert_kulcsok_keszlete_ROGZITETT` erre külön ráfeszül.
    """
    if isinstance(annotacio, type):
        return annotacio.__name__
    return str(annotacio)


def _szekciobol(cls, elonev: str, kornyezet) -> tuple[object, set[str]]:
    """Egy szekció példánya az env-ből. Visszaadja a FELISMERT kulcsokat is."""
    kwargs, ismert = {}, set()
    for f in fields(cls):
        tipus = _tipusnev(f.type)
        if tipus not in ("str", "int", "float", "bool"):
            continue
        kulcs = f"FREEDROID_{elonev}_{f.name.upper()}"
        ismert.add(kulcs)
        if (nyers := kornyezet.get(kulcs)) is not None:
            kwargs[f.name] = _ertek(kulcs, nyers, tipus)
    return cls(**kwargs), ismert


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """A hatályos beállítások: alapértelmezések + `FREEDROID_<SZEKCIÓ>_<MEZŐ>` felülírás.

    A validáció VÁLTOZATLANUL fut (a dataclassok `__post_init__`-je), tehát egy
    tartományon kívüli env-érték ugyanúgy indulásnál bukik, mint egy rossz default.
    """
    kornyezet = os.environ if env is None else env
    reszek, ismert = {}, set()
    for elonev, (mezo, cls) in _SZEKCIOK.items():
        reszek[mezo], kulcsok = _szekciobol(cls, elonev, kornyezet)
        ismert |= kulcsok

    # ELGÉPELT FELÜLÍRÁS: némán az alapértelmezéssel futni pontosan az a csendes
    # sodródás, ami ellen ez a modul készült. Figyelmeztetés, nem hiba: egy ismeretlen
    # FREEDROID_* változó miatt a robot ne álljon meg a színpadon.
    for kulcs in sorted(k for k in kornyezet if k.startswith("FREEDROID_")):
        if kulcs not in ismert and kulcs not in _EGYEB_ENV:
            print(f"settings: ISMERETLEN felülírás, FIGYELMEN KÍVÜL HAGYVA: {kulcs} "
                  f"(elgépelés? az alapértelmezés marad érvényben)", file=sys.stderr)
    return Settings(**reszek)
