"""Átirat-napló: mit hallott a Whisper, mi ment a RAG-ra, mit válaszolt melyik modell.

Egy sor = egy teljes interakció, JSONL-ben. A cél NEM a hibakeresés általában, hanem
egyetlen konkrét kérdés megválaszolása a Pi-n, élő magyar beszéddel:

    hol romlik el a lánc — a felismerésnél, a keresésnél vagy a modellnél?

Ez a három szakasz külön mérhető, és a 2026-08-07-i mérés szerint nem egyformán
törékeny. A RAG lexikai (BM25), ezért egy elrontott tulajdonnév nem rosszabb
találatot ad, hanem SEMMIT: „Mi az a Yotengrit?" -> „Mi az a jó tengrit?" esetén a
találat üres, míg a hiányzó írásjel, a kisbetű és a töltelékszó nem zavarja. Az
összetett szó szétírása („nádszál" -> „nád szál") rossz chunkot hoz. Ezért logoljuk
KÜLÖN a nyers átiratot és a betalált chunkokat: e kettőből azonnal látszik, hogy a
Whisper értette félre, vagy a keresés nem találta meg a jót.

A napló PERZISZTENS útvonalra ír (nem /run-ba, ami tmpfs és újraindításkor törlődik),
mert utólag akarjuk elemezni.

    FREEDROID_TRANSCRIPT_LOG=/var/log/freedroid/transcript.jsonl
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from freedroid.config.settings import debug_mode

DEFAULT_PATH = Path(
    os.environ.get("FREEDROID_TRANSCRIPT_LOG", "/var/log/freedroid/transcript.jsonl"))


@dataclass
class Interakcio:
    """Egy kör a láncból. Minden szakasz külön mezőben — ez a lényeg."""

    hallott: str                       # a Whisper NYERS átirata, változtatás nélkül
    valasz: str = ""                   # amit a modell mondott
    forras: str = ""                   # "cloud" | "edge" | "safe" — MELYIK ág felelt
    modell: str = ""                   # a konkrét modellnév, pl. "szabi-8b-v12"
    hatter_indok: str = ""             # MIÉRT az az ág — a teljes döntési nyom
    rag_chunkok: list[str] = field(default_factory=list)   # betalált chunk-id-k
    rag_cimek: list[str] = field(default_factory=list)     # …és a címük, olvashatóan
    prompt: str = ""                   # ami TÉNYLEG a modellhez ment (grounding-gal)
    toolok: list[str] = field(default_factory=list)        # a kiparsolt tool-hívások
    stt_ms: int | None = None
    llm_ms: int | None = None
    hiba: str = ""                     # ha a kör elhasalt, ide jön a rövid ok


def log(esemeny: Interakcio, path: Path | None = None) -> None:
    """Egy sort fűz a naplóhoz — CSAK debug posztúrában. SOSEM dob kivételt.

    🔴 A KAPUT ITT tesszük, egyetlen helyen, nem a hívóknál: ez az a fájl, ami a Pi
    egyetlen NEM publikus és NEM forgatható adatát tartalmazza (a Teremtő nyers,
    elhangzott mondatait). Egy kihagyott kapu egy hívónál csendben visszahozná az egész
    kockázatot — egy WireGuard-kulcsot lehet forgatni, egy kiszivárgott beszélgetést nem.
    A polaritás és az indoklás: `freedroid.config.settings.debug_mode()`.

    A színpadon egy tele lemez vagy egy hiányzó könyvtár nem némíthatja el Szabit,
    ezért a hibát csak jelezzük a stderr-en (a journald elkapja) és megyünk tovább.

    A `default=str` és az `errors="replace"` NEM kozmetika: az első változat csak
    `OSError`-t kapott el, és két út kiszökött rajta (mérve, nem feltételezve):
      - nem szerializálható mező -> `TypeError` (elég egy `Path` a `toolok`-ban),
      - lone surrogate a stringben -> `UnicodeEncodeError`, ami `ValueError`, nem
        `OSError`. Ez pont a `hallott` mezőn valós: az a Whisper NYERS átirata, és
        egy `surrogateescape`-pel dekódolt hibás bájtsor egyenesen ide kerül.
    A két beállítás azért jobb, mint a puszta elnyelés, mert a sor MEGMARAD (rontott
    karakterrel vagy `str()`-elt mezővel) ahelyett, hogy némán elveszne — a napló
    egésze pont a diagnosztikáért van. Az `except Exception` a maradék hálója.

    EGY ÍRÓT feltételez. Text-módban a `prompt` könnyen 8 KB fölé megy, ilyenkor egy
    sor több `write()`-ban megy ki, és párhuzamos íróval összefésülődhet. Ma egyetlen
    orchestrator-hurok naplóz, tehát nem éles; ha valaha több szál/folyamat írna, egy
    `os.write` egy `O_APPEND` fd-re a javítás. A kár így is lokális marad: az `olvas()`
    a sérült sort átugorja, a fájl egésze nem válik elemezhetetlenné.
    """
    if not debug_mode():
        return
    cel = path or DEFAULT_PATH
    sor = {"ts": datetime.now(UTC).isoformat(timespec="seconds"),
           **asdict(esemeny)}
    try:
        cel.parent.mkdir(parents=True, exist_ok=True)
        with cel.open("a", encoding="utf-8", errors="replace") as f:
            f.write(json.dumps(sor, ensure_ascii=False, default=str) + "\n")
    except Exception as e:  # noqa: BLE001 — a napló SOHA nem állíthatja meg a robotot
        print(f"transcript: nem tudom írni a naplót ({cel}): {e}", file=sys.stderr)


def olvas(path: Path | None = None) -> list[dict]:
    """A napló beolvasása elemzéshez. A sérült sorokat átugorja, nem hasal el rajtuk."""
    cel = path or DEFAULT_PATH
    if not cel.exists():
        return []
    ki = []
    with cel.open(encoding="utf-8") as f:
        for sor in f:
            if sor.strip():
                try:
                    ki.append(json.loads(sor))
                except ValueError:
                    continue
    return ki
